import asyncio
import json
from types import SimpleNamespace

import httpx
import openai
import pytest

import free_llm as fl


def spec(name, **kw):
    return {"name": name, "env_key": f"{name.upper()}_API_KEY", "base_url": "http://fake/v1",
            "model": f"{name}-model", "supports_json": kw.pop("supports_json", True), **kw}


def reply(text):
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


def status_error(code, body="error", headers=None):
    req = httpx.Request("POST", "http://fake/v1/chat/completions")
    resp = httpx.Response(code, request=req, headers=headers or {}, text=body)
    return openai.APIStatusError(body, response=resp, body=None)


class FakeClient:
    """Plays back a script of replies/exceptions for one provider."""

    def __init__(self, *script):
        self.script = list(script)
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self._create))

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return reply(item)


def make(monkeypatch, *pairs):
    """pairs: (spec, FakeClient). Returns the rotation client."""
    for s, _ in pairs:
        monkeypatch.setenv(s["env_key"], "test-key")
    client = fl.FreeLLMClient(providers=[s for s, _ in pairs])
    for prov, (_, fake) in zip(client.providers, pairs):
        prov._client = fake
    return client


def ask(client, **kw):
    return asyncio.run(client.chat.completions.create(messages=[{"role": "user", "content": "hi"}], **kw))


# ---------------- rotation ----------------

def test_first_working_provider_answers(monkeypatch):
    c = make(monkeypatch, (spec("a"), FakeClient("hello")), (spec("b"), FakeClient("unused")))
    assert ask(c).choices[0].message.content == "hello"
    assert c.providers[0].ok_count == 1 and c.providers[0].status() == "ready"


@pytest.mark.parametrize("bad", ["", "   ", "Here's a thinking process: first..."])
def test_empty_or_reasoning_reply_is_a_failure_and_rotates(monkeypatch, bad):
    c = make(monkeypatch, (spec("a"), FakeClient(bad)), (spec("b"), FakeClient("real answer")))
    assert ask(c).choices[0].message.content == "real answer"
    assert c.providers[0].fail_count == 1 and not c.providers[0].available()


def test_closed_think_block_is_stripped(monkeypatch):
    c = make(monkeypatch, (spec("a"), FakeClient("<think>hmm</think>The answer")))
    assert ask(c).choices[0].message.content == "The answer"


def test_json_mode_reply_is_unfenced(monkeypatch):
    c = make(monkeypatch, (spec("a"), FakeClient('Sure! ```json\n{"x": 1}\n``` hope that helps')))
    out = ask(c, response_format={"type": "json_object"}).choices[0].message.content
    assert json.loads(out) == {"x": 1}


def test_broken_json_rotates(monkeypatch):
    c = make(monkeypatch, (spec("a"), FakeClient("{not json")), (spec("b"), FakeClient('{"ok": true}')))
    assert json.loads(ask(c, response_format={"type": "json_object"}).choices[0].message.content) == {"ok": True}


def test_provider_without_json_support_never_sees_the_hint(monkeypatch):
    fake = FakeClient('{"a": 1}')
    c = make(monkeypatch, (spec("a", supports_json=False), fake))
    ask(c, response_format={"type": "json_object"})
    assert "response_format" not in fake.calls[0]


def test_json_mode_400_sheds_the_hint_and_retries_same_provider(monkeypatch):
    fake = FakeClient(status_error(400, "response_format not supported"), '{"a": 1}')
    c = make(monkeypatch, (spec("a"), fake))
    assert json.loads(ask(c, response_format={"type": "json_object"}).choices[0].message.content) == {"a": 1}
    assert "response_format" in fake.calls[0] and "response_format" not in fake.calls[1]
    assert c.providers[0].supports_json is False


# ---------------- error classification ----------------

@pytest.mark.parametrize("err,disabled", [
    (status_error(401, "invalid key"), True),
    (status_error(400, "Please pass a valid API key"), True),        # Gemini's bad-key shape
    (status_error(402, "payment required"), True),
    (status_error(404, "model not found"), True),
    (status_error(429, "slow down", {"x-ratelimit-limit-req-minute": "0"}), True),   # zero quota
    (status_error(429, "slow down", {"retry-after": "30"}), False),
    (status_error(403, "Access denied. Please check your network settings."), False),  # VPN, not the key
    (status_error(503, "overloaded"), False),
])
def test_errors_disable_or_cool_correctly(monkeypatch, err, disabled):
    c = make(monkeypatch, (spec("a"), FakeClient(err)), (spec("b"), FakeClient("ok")))
    assert ask(c).choices[0].message.content == "ok"
    a = c.providers[0]
    assert bool(a.disabled_reason) is disabled
    assert not a.available()


def test_all_providers_failing_raises_with_reasons(monkeypatch):
    c = make(monkeypatch, (spec("a"), FakeClient(status_error(401, "bad key"))),
             (spec("b"), FakeClient("")))
    with pytest.raises(fl.AllProvidersExhausted) as exc:
        ask(c)
    assert "a: 401" in str(exc.value) and "empty reply" in str(exc.value)


def test_unconfigured_providers_are_skipped_and_reported(monkeypatch):
    c = fl.FreeLLMClient(providers=[spec("nokey")])
    assert "NO PROVIDERS CONFIGURED" in c.status_line()


def test_untested_key_is_not_reported_as_ready(monkeypatch):
    """Regression: a boot line of six "ready" providers hid a table where all six were dead."""
    c = make(monkeypatch, (spec("a"), FakeClient()))
    assert c.providers[0].status() == "key set, untested"


def test_free_llm_order_reorders_and_filters(monkeypatch):
    monkeypatch.setenv("FREE_LLM_ORDER", "b, a, zzz")
    c = fl.FreeLLMClient(providers=[spec("a"), spec("b"), spec("c")])
    assert [p.name for p in c.providers] == ["b", "a"]


# ---------------- helpers ----------------

def test_retry_after_header_and_gemini_body():
    assert fl._retry_after(status_error(429, "x", {"retry-after": "12"})) == 12
    assert fl._retry_after(status_error(429, "x", {"retry-after": "99999"})) == 300     # capped
    gem = status_error(429, "{'error': {'details': [{'retryDelay': '13443s'}]}}")
    assert fl._retry_after(gem) == 13443
    assert fl._retry_after(status_error(429, "no hint")) == 0


@pytest.mark.parametrize("text,expected", [
    ('{"a": 1}', '{"a": 1}'),
    ('```json\n{"a": 1}\n```', '{"a": 1}'),
    ('Here is the JSON: {"a": 1} thanks', '{"a": 1}'),
    ('{"code": "```inside```"}', '{"code": "```inside```"}'),      # valid JSON with a fence inside a value
    ("no json at all", "no json at all"),
])
def test_coerce_json(text, expected):
    assert fl._coerce_json(text) == expected
