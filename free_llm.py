#!/usr/bin/env python
"""
free_llm.py - rotate across free-tier LLM providers so the scanner costs nothing.

WHY THIS EXISTS
The scanner used to hold one AsyncOpenAI client on a paid key. Every free tier
worth using speaks the OpenAI wire format, so the cheapest possible change is
not to rewrite the call sites but to hand them a client that LOOKS like
AsyncOpenAI and quietly tries providers in order until one answers.

    client = FreeLLMClient()
    resp = await client.chat.completions.create(model=..., messages=[...])
    resp.choices[0].message.content        # unchanged, real SDK object

The provider's own response object is returned untouched, so nothing
downstream needs adapting.

DESIGN RULES, each of which is a bug that would otherwise happen:

* The caller's `model=` is IGNORED. Call sites pass OPENAI_MODEL
  ('gpt-4o-mini'); no free provider serves it, so honouring it would 404 the
  whole rotation. Each provider names its own model in the table below.

* Permanent failures are separated from transient ones. A 401 (bad key) or 404
  (model id retired) disables that provider for the life of the process; a 429
  or 5xx only puts it on a cooldown. Treating a dead model id as "busy, retry
  later" makes the rotation walk corpses forever, and every failure then looks
  identical to "all free tiers throttled" - which is the one thing this module
  exists to distinguish.

* max_retries=0 on every client, plus a per-provider timeout and a total
  budget. The SDK's own retries multiply against our rotation; this codebase
  has already seen a 2-3s call land at ~96s wall-clock (see the note near the
  bottom of basesolanascan.py) and six providers retrying twice each would
  reproduce it exactly.

* response_format={"type":"json_object"} is the highest-risk argument. Support
  is uneven: some providers honour it, some reject it with a 400, some accept
  it and still wrap the reply in a ```json fence. understand_intent() feeds the
  reply straight to json.loads with no fence-stripping, so we (a) drop the
  parameter for providers flagged as not supporting it, (b) retry once without
  it on a 400 and remember, and (c) strip fences from every reply regardless.

* Nothing here ever falls back to a paid key. When the table is exhausted it
  raises AllProvidersExhausted and the caller degrades. That is the point.

Text is ASCII on purpose: this runs on a Windows console whose stdout is
cp1252, and a stray non-encodable character in a log line takes the trader out.

    python free_llm.py         # selftest - pings every configured provider
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)


class AllProvidersExhausted(RuntimeError):
    """Every free provider is disabled, cooling down, or unconfigured."""


# ---------------------------------------------------------------------------
# the provider table
# ---------------------------------------------------------------------------
# Deliberately DATA, not branches. Free tiers churn hard - models get retired
# and limits get cut with no notice - so adding, reordering or dropping a
# provider is an edit to this list and nothing else.
#
# Order is the rotation order: fastest and most generous first. Every entry is
# skipped silently when its env key is absent, so a partly-configured install
# just works with whatever keys exist.
#
# Per-entry overrides, so a retired model id can be fixed from .env without
# touching code:   FREE_LLM_<NAME>_MODEL=some-new-model-id
# Reorder or subset the rotation with:   FREE_LLM_ORDER=gemini,mistral,nvidia

PROVIDERS = [
    # Re-verified 2026-10-03 after the whole table had silently died: every
    # model below answered a real analyst prompt cleanly AND honoured json
    # mode, unless the comment says otherwise. The short "say ok" probe is not
    # enough - nemotron-3.5-lightning passed it and then printed "Here's a
    # thinking process:" into a real risk note.
    {
        "name": "gemini",
        "env_key": "GEMINI_API_KEY",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        # 1.2s, clean, json OK. gemini-2.5-flash-lite is retired (404).
        # Free quota is PER DAY PER MODEL, so the second gemini entry below is
        # a separate bucket on the same key, not a duplicate.
        # Note: no "models/" prefix, despite that being how /models lists them.
        "model": "gemini-3.5-flash-lite",
        "supports_json": True,
    },
    {
        "name": "mistral",
        "env_key": "MISTRAL_API_KEY",
        "base_url": "https://api.mistral.ai/v1",
        # mistral-small-latest and mistral-medium-latest now come back 429 with
        # x-ratelimit-limit-req-minute: 0 - a ZERO quota on this plan, not
        # busy. ministral-14b answers in ~1.6s and honours json mode (it may
        # nest the object, which json.loads still accepts).
        "model": "ministral-14b-latest",
        "supports_json": True,
    },
    {
        "name": "groq",
        "env_key": "GROQ_API_KEY",
        "base_url": "https://api.groq.com/openai/v1",
        # UNVERIFIED. Groq 403s every request ("Access denied. Please check
        # your network settings") while this box is on a VPN exit (PacketHub
        # ASN) - it blocks VPN/datacenter IPs, the key is not the problem. On
        # earlier runs when it WAS reachable it 404'd this model id, so expect
        # to need FREE_LLM_GROQ_MODEL=<id from /models> once the VPN is off.
        "model": "llama-3.3-70b-versatile",
        "supports_json": True,
    },
    {
        "name": "gemini25",
        "env_key": "GEMINI_API_KEY",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        # Same key as "gemini", separate 20/day quota bucket. Small, but free.
        "model": "gemini-2.5-flash",
        "supports_json": True,
    },
    {
        "name": "openrouter",
        "env_key": "OPENROUTER_API_KEY",
        "base_url": "https://openrouter.ai/api/v1",
        # UNVERIFIED. gpt-oss-20b is no longer free (404 "use the paid slug").
        # Every decent :free model was "rate-limited upstream" on 2026-10-03;
        # this one is the strongest on the list. Later that day it DID serve
        # the bot's real intent + analyst calls cleanly (json mode shed, text
        # coerced), so it sits ahead of nvidia. The only :free model that
        # answered was a code model (cohere/north-mini-code), not worth it.
        "model": "qwen/qwen3.8-27b:free",
        "supports_json": True,
    },
    {
        "name": "ollama",
        # Local, on this PC: no key, no daily cap, no VPN block - the one entry
        # that cannot be rate-limited, so the notes never go fully dark.
        # Models live on the external G: drive (OLLAMA_MODELS=G:\Ollama\models).
        # Measured 2026-10-03 with OLLAMA_IGPU_ENABLE=1 (Radeon 860M, all 33
        # layers offloaded): 8s risk note, 4-5s json intent, json OK. llama3.2:3b
        # is faster but misread "is $DOGWIF a rug?" as a question about a rug.
        # The FIRST call after a load reads ~5GB off the external drive (~53s),
        # so run the server with OLLAMA_KEEP_ALIVE=-1 to keep it loaded.
        # Turn it off with FREE_LLM_OLLAMA=0.
        "env_key": "FREE_LLM_OLLAMA",
        "keyless": True,
        "local": True,
        "timeout": 30,
        "base_url": "http://%s/v1" % (os.getenv("OLLAMA_HOST") or "127.0.0.1:11434"),
        "model": "llama3.1:8b",
        "supports_json": True,
    },
    {
        "name": "nvidia",
        "env_key": "NVIDIA_API_KEY",
        "base_url": "https://integrate.api.nvidia.com/v1",
        # The old nemotron-super-49b reached end of life 2026-08-26 (410 Gone).
        # llama-3.2-90b: clean note, json OK, ~15s on a real prompt - slow but
        # inside the 20s per-provider timeout. gemma-4-31b is also clean but
        # measured 20-27s, so it always timed out. Do NOT use
        # nemotron-3.5-lightning: it leaks its reasoning. deepseek-v4.1-flash
        # and glm-5.3-flash timed out at 45s.
        "model": "meta/llama-3.2-90b-vision-instruct",
        "supports_json": True,
    },
    {
        "name": "cerebras",
        "env_key": "CEREBRAS_API_KEY",
        "base_url": "https://api.cerebras.ai/v1",
        # DEAD unless billing is added: every model on this key returns 402
        # "Payment required". gemma-4-31b was archived. Kept last so it costs
        # one call per process before disabling itself.
        "model": "qwen-3.8-27b",
        "supports_json": True,
    },
]

# How long a provider sits out after a soft failure, when it does not tell us.
COOLDOWN_RATE_LIMIT = float(os.getenv("FREE_LLM_COOLDOWN_429", "60"))
COOLDOWN_SERVER_ERR = float(os.getenv("FREE_LLM_COOLDOWN_5XX", "30"))

# One provider's share of the clock, and the ceiling on a whole rotation.
# 20s rather than 15s because groq was measured at 13.8s on a cold connection -
# uncomfortably close to a limit that would have knocked out the best provider
# in the table on the first call of every run.
PER_PROVIDER_TIMEOUT = float(os.getenv("FREE_LLM_TIMEOUT", "20"))
TOTAL_BUDGET = float(os.getenv("FREE_LLM_TOTAL_BUDGET", "60"))


def _fence_strip(text: str) -> str:
    """
    Unwrap a ```json ... ``` fence if the model added one.

    Applied to every reply, not just json-mode ones: understand_intent() hands
    the string straight to json.loads, and a fenced reply there drops the user
    into the "I'm having trouble understanding" path with no clue why.
    """
    if not text:
        return text
    stripped = text.strip()
    # Not anchored to the end: a model that adds a trailing "Hope that helps!"
    # after the closing fence is common, and an anchored match misses it.
    match = re.search(r"```(?:json|JSON)?\s*(.*?)\s*```", stripped, re.S)
    return match.group(1).strip() if match else stripped


def _coerce_json(text: str) -> str:
    """
    Best effort at making a reply that json.loads will accept.

    Needed because understand_intent() parses with no fence-stripping and no
    error tolerance, while the providers flagged supports_json=False never got
    the response_format hint at all - so their replies routinely arrive as
    'Sure! ```json {...} ```' or 'Here is the JSON: {...}'. Both parse to
    nothing and the user just sees "I'm having trouble understanding".

    Same shape as _extract_json in the jobsearch vision module: unwrap a fence
    if there is one, otherwise take the outermost braces. If neither yields
    valid JSON, hand back the fence-stripped text and let the caller's own
    except decide - guessing further would be inventing content.
    """
    # Raw first: already-valid JSON with a ``` inside a string value would be
    # cut at that fence by _fence_strip and then be unrecoverable.
    try:
        json.loads(text.strip())
        return text.strip()
    except ValueError:
        pass
    candidate = _fence_strip(text)
    try:
        json.loads(candidate)
        return candidate
    except ValueError:
        pass
    start, end = candidate.find("{"), candidate.rfind("}")
    if start != -1 and end > start:
        inner = candidate[start:end + 1]
        try:
            json.loads(inner)
            return inner
        except ValueError:
            pass
    return candidate


class _Provider:
    """One free tier, plus what we have learned about it at runtime."""

    def __init__(self, spec: dict):
        self.name = spec["name"]
        self.base_url = spec["base_url"]
        self.env_key = spec["env_key"]
        self.api_key = (os.getenv(spec["env_key"]) or "").strip()
        # Keyless (local Ollama): on unless its switch is set to 0, and the SDK
        # still wants some non-empty key string.
        if spec.get("keyless"):
            self.api_key = "" if self.api_key == "0" else "ollama"
        self.timeout = float(spec.get("timeout") or PER_PROVIDER_TIMEOUT)
        # A local server's 404 means "model not loaded / drive unplugged", which
        # fixes itself; it must not disable the provider for the whole run.
        self.local = bool(spec.get("local"))
        env_model = os.getenv("FREE_LLM_%s_MODEL" % self.name.upper())
        self.model = (env_model or spec["model"]).strip()
        self.supports_json = bool(spec.get("supports_json"))
        self.disabled_reason = ""     # set once, permanent for this process
        self.cooldown_until = 0.0     # transient
        self.ok_count = 0
        self.fail_count = 0
        self._client = None

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def available(self) -> bool:
        if not self.configured or self.disabled_reason:
            return False
        return time.monotonic() >= self.cooldown_until

    def status(self) -> str:
        if not self.configured:
            return "no key (%s)" % self.env_key
        if self.disabled_reason:
            return "DISABLED: %s" % self.disabled_reason
        left = self.cooldown_until - time.monotonic()
        if left > 0:
            return "cooling down %ds" % int(left)
        # "ready" used to print for a key that had never been tried, so a boot
        # line of six "ready" providers hid a table where all six were dead.
        if not self.ok_count and not self.fail_count:
            return "key set, untested"
        return "ready"

    def client(self):
        # Built lazily and kept: constructing an AsyncOpenAI per call leaks
        # connection pools on a process that runs for days.
        if self._client is None:
            from openai import AsyncOpenAI
            self._client = AsyncOpenAI(
                api_key=self.api_key,
                base_url=self.base_url,
                timeout=self.timeout,
                max_retries=0,          # rotation IS the retry; see module docstring
            )
        return self._client

    def disable(self, reason: str) -> None:
        self.disabled_reason = reason
        logger.warning("free_llm: disabling %s for this run - %s", self.name, reason)

    def cool(self, seconds: float, why: str) -> None:
        self.cooldown_until = time.monotonic() + seconds
        logger.info("free_llm: %s out for %ds (%s)", self.name, int(seconds), why)


def _retry_after(exc) -> float:
    """Seconds the provider asked us to wait, or 0 if it did not say."""
    try:
        headers = getattr(getattr(exc, "response", None), "headers", None) or {}
        raw = headers.get("retry-after") or headers.get("Retry-After")
        if raw:
            # Only the delta-seconds form; an HTTP-date here is rare and a bad
            # parse would be worse than falling back to our own default.
            return max(0.0, min(float(raw), 300.0))
    except (TypeError, ValueError):
        pass
    # Gemini sends no header; the wait is in the body as "retryDelay": "13443s"
    # (str(exc) renders that body as a Python dict, so quotes may be single).
    # Its free quota is PER DAY, so the delay is hours, and honouring it is the
    # whole point - capping it at minutes means re-hitting a spent daily quota
    # on every single call for the rest of the day.
    match = re.search(r"""['"]retryDelay['"]\s*:\s*['"](\d+(?:\.\d+)?)s['"]""", str(exc))
    if match:
        return max(0.0, min(float(match.group(1)), 86400.0))
    return 0.0


def _zero_quota(exc) -> bool:
    """
    A 429 that will never clear: the plan's limit on this model is 0.

    Mistral answers models its free plan excludes with 429 plus
    x-ratelimit-limit-req-minute: 0. Treated as "busy" that costs one wasted
    round trip every cooldown, forever, and reads as throttling in the logs.
    """
    try:
        headers = getattr(getattr(exc, "response", None), "headers", None) or {}
        return str(headers.get("x-ratelimit-limit-req-minute", "")).strip() == "0"
    except Exception:
        return False


class FreeLLMClient:
    """
    Drop-in stand-in for AsyncOpenAI, for chat.completions.create only.

    Anything else the SDK offers is deliberately absent - if a future call site
    needs embeddings it should fail loudly here rather than silently reach for
    a paid client.
    """

    def __init__(self, providers=None):
        specs = providers if providers is not None else PROVIDERS
        order = (os.getenv("FREE_LLM_ORDER") or "").strip()
        if order:
            wanted = [n.strip().lower() for n in order.split(",") if n.strip()]
            by_name = {s["name"]: s for s in specs}
            specs = [by_name[n] for n in wanted if n in by_name]
        self.providers = [_Provider(s) for s in specs]
        self.chat = _Chat(self)

    # -- introspection, for the selftest and the operator ------------------

    @property
    def configured(self) -> list:
        return [p for p in self.providers if p.configured]

    def status_line(self) -> str:
        if not self.configured:
            return "free LLM rotation: NO PROVIDERS CONFIGURED (%s)" % (
                ", ".join(p.env_key for p in self.providers))
        parts = ["%s[%s]" % (p.name, p.status()) for p in self.providers if p.configured]
        return "free LLM rotation: " + ", ".join(parts)

    # -- the actual rotation ----------------------------------------------

    async def _create(self, **kwargs):
        kwargs.pop("model", None)          # see module docstring
        deadline = time.monotonic() + TOTAL_BUDGET
        tried, problems = [], []

        for prov in self.providers:
            if not prov.available():
                if prov.configured:
                    problems.append("%s: %s" % (prov.name, prov.status()))
                continue
            if time.monotonic() >= deadline:
                problems.append("total budget of %ds spent" % int(TOTAL_BUDGET))
                break

            tried.append(prov.name)
            resp = await self._attempt(prov, kwargs, problems)
            if resp is not None:
                return resp

        raise AllProvidersExhausted(
            "no free LLM provider answered (tried: %s). %s"
            % (", ".join(tried) or "none", "; ".join(problems) or "nothing configured"))

    async def _attempt(self, prov: _Provider, kwargs: dict, problems: list):
        """One provider, at most two calls (the second only to shed json mode)."""
        import openai

        call = dict(kwargs)
        # Remembered before the parameter is dropped: a provider that never saw
        # the json hint is exactly the one whose reply needs coercing.
        wants_json = "response_format" in call
        if wants_json and not prov.supports_json:
            call.pop("response_format")

        for shed_json in (False, True):
            if shed_json:
                call.pop("response_format", None)
            try:
                resp = await prov.client().chat.completions.create(
                    model=prov.model, **call)

            except openai.APIStatusError as exc:
                status = getattr(exc, "status_code", 0)
                detail = "%s %s" % (status, str(exc)[:120])

                # Not every provider answers a bad key with 401: Gemini returns
                # 400 INVALID_ARGUMENT "Please pass a valid API key" (verified
                # against the live endpoint). Sniff the body before falling
                # through to the json-mode branch, or a bad Gemini key gets
                # reported as a malformed request AND wastes a retry shedding
                # json mode that was never the problem.
                looks_like_auth = re.search(r"api.?key|unauthor|authenticat",
                                            str(exc), re.I)

                # Groq's 403 for a VPN/datacenter IP. It is NOT a key problem,
                # and reporting it as "auth rejected" sent the fix to the wrong
                # place. A cooldown, not a disable: the VPN can go off mid-run.
                blocked_network = status == 403 and re.search(
                    r"network settings|access denied", str(exc), re.I)

                if blocked_network:
                    prov.cool(1800, "blocked by network - VPN on? key is fine")
                elif status in (401, 403) or (status == 400 and looks_like_auth):
                    prov.disable("auth rejected (check %s)" % prov.env_key)
                elif status == 404 and prov.local:
                    prov.cool(300, "model not available locally - external drive unplugged?")
                elif status in (404, 410):
                    # 410 is NVIDIA's "model reached end of life".
                    prov.disable("model '%s' not found or retired - set FREE_LLM_%s_MODEL"
                                 % (prov.model, prov.name.upper()))
                elif status == 402:
                    prov.disable("payment required - free tier gone on this account")
                elif status == 429 and _zero_quota(exc):
                    prov.disable("plan quota for '%s' is 0 - set FREE_LLM_%s_MODEL"
                                 % (prov.model, prov.name.upper()))
                elif status == 429:
                    prov.cool(_retry_after(exc) or COOLDOWN_RATE_LIMIT, "rate limited")
                elif status == 400 and "response_format" in call and not shed_json:
                    # Very likely the json-mode parameter. Shed it and retry
                    # once; the unconditional fence-strip below covers the
                    # reply now arriving as fenced prose.
                    prov.supports_json = False
                    logger.info("free_llm: %s rejected json mode, retrying without",
                                prov.name)
                    continue
                elif status >= 500:
                    prov.cool(COOLDOWN_SERVER_ERR, "server error")
                else:
                    prov.disable("rejected the request (%s)" % detail)

                prov.fail_count += 1
                problems.append("%s: %s" % (prov.name, detail))
                return None

            except (openai.APITimeoutError, openai.APIConnectionError) as exc:
                prov.cool(COOLDOWN_SERVER_ERR, "unreachable")
                prov.fail_count += 1
                problems.append("%s: %s" % (prov.name, type(exc).__name__))
                return None

            except Exception as exc:                       # never take the run down
                prov.cool(COOLDOWN_SERVER_ERR, "unexpected error")
                prov.fail_count += 1
                problems.append("%s: %s %s" % (prov.name, type(exc).__name__, str(exc)[:80]))
                return None

            # Success. Normalise the text in place - the caller gets the real
            # SDK object, so response.choices[0].message.content keeps working.
            try:
                msg = resp.choices[0].message
                raw = msg.content or ""
            except (AttributeError, IndexError):
                problems.append("%s: malformed response" % prov.name)
                prov.fail_count += 1
                return None

            # An empty reply is a FAILURE, not a success with nothing in it.
            # Reasoning models (gpt-oss, nemotron) spend the token budget on
            # hidden reasoning and can return content="" with a 200 OK. Accepted
            # as-is that becomes a blank analyst note on a real token alert,
            # while the rotation reports success and never tries the next
            # provider - the worst combination available.
            if not raw.strip():
                prov.cool(COOLDOWN_SERVER_ERR, "returned an empty reply")
                prov.fail_count += 1
                problems.append("%s: empty reply (reasoning model out of tokens?)"
                                % prov.name)
                return None

            # Reasoning leaks are a failure too. Free hosts swap upstreams, and
            # a model that leaks its chain of thought ("Here's a thinking
            # process:") would post that straight into a token alert. Closed
            # <think> blocks are just stripped; an open-ended leak is rejected.
            raw = re.sub(r"<(think|thought)>.*?</\1>", "", raw, flags=re.S | re.I).strip()
            if not raw or re.match(r"(here'?s a thinking process|thinking process:|<think|<thought)",
                                   raw, re.I):
                prov.cool(COOLDOWN_SERVER_ERR, "leaked its reasoning")
                prov.fail_count += 1
                problems.append("%s: reply was reasoning, not an answer" % prov.name)
                return None

            msg.content = _coerce_json(raw) if wants_json else _fence_strip(raw)

            # Unparseable JSON is a failure too, for the same reason as the
            # empty reply: the caller json.loads it with no fallback, so
            # accepting it means "I'm having trouble understanding" while the
            # next provider in the table never gets asked.
            if wants_json:
                try:
                    json.loads(msg.content)
                except ValueError:
                    prov.cool(COOLDOWN_SERVER_ERR, "returned broken JSON")
                    prov.fail_count += 1
                    problems.append("%s: json mode reply did not parse" % prov.name)
                    return None

            prov.ok_count += 1
            return resp

        return None


class _Chat:
    def __init__(self, parent):
        self.completions = _Completions(parent)


class _Completions:
    def __init__(self, parent):
        self._parent = parent

    async def create(self, **kwargs):
        return await self._parent._create(**kwargs)


# ---------------------------------------------------------------------------
# selftest
# ---------------------------------------------------------------------------

async def _selftest() -> int:
    """
    Ping every configured provider individually and print a table.

    This is the check that tells a working rotation apart from a table of dead
    endpoints - the failure mode that otherwise looks exactly like success,
    because the scanner degrades silently either way.
    """
    print("free_llm selftest")
    print("=" * 74)

    rows, working = [], 0
    for spec in PROVIDERS:
        prov = _Provider(spec)
        if not prov.configured:
            rows.append((prov.name, prov.model, "-- no key --", ""))
            continue

        solo = FreeLLMClient(providers=[spec])
        started = time.monotonic()
        try:
            # NOT max_tokens=5. Reasoning models (gpt-oss, nemotron) spend the
            # budget on hidden reasoning and return an empty completion, which
            # the rotation now correctly counts as a failure - so a tiny probe
            # would fail providers that are perfectly healthy at the 300-700
            # tokens the scanner actually asks for.
            # A real one-line question, not "say ok": models that leak their
            # reasoning pass a one-word probe and fail on actual work.
            resp = await solo._create(
                messages=[{"role": "user",
                           "content": "In one sentence, what is a rug pull in crypto?"}],
                max_tokens=300, temperature=0)
            took = "%.1fs" % (time.monotonic() - started)
            reply = (resp.choices[0].message.content or "").strip()[:20]
            rows.append((prov.name, prov.model, "OK  %s" % took, repr(reply)))
            working += 1
        except AllProvidersExhausted as exc:
            rows.append((prov.name, prov.model, "FAIL", str(exc)[:44]))
            continue

        # Does json mode survive on this provider?
        try:
            resp = await solo._create(
                messages=[{"role": "user",
                           "content": 'Return JSON only: {"ok": true}'}],
                max_tokens=200, temperature=0,     # same reasoning-budget trap
                response_format={"type": "json_object"})
            import json
            json.loads((resp.choices[0].message.content or "").strip())
            rows[-1] = rows[-1][:3] + ("json OK",)
        except Exception:
            rows[-1] = rows[-1][:3] + ("json NO - text only",)

    print("%-12s %-34s %-11s %s" % ("PROVIDER", "MODEL", "RESULT", "NOTE"))
    print("-" * 74)
    for name, model, result, note in rows:
        print("%-12s %-34s %-11s %s" % (name, model[:34], result, note))
    print("-" * 74)
    print("%d of %d configured providers answered." % (working, len(
        [s for s in PROVIDERS if _Provider(s).configured])))

    if working == 0:
        print("\nNOTHING IS WORKING. Add at least one free key to .env:")
        for spec in PROVIDERS:
            print("  %-20s %s" % (spec["env_key"], spec["base_url"]))
        return 1
    if working == 1:
        print("\nOnly one provider works - there is no rotation, just a single\n"
              "point of failure. Add a second key.")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    raise SystemExit(asyncio.run(_selftest()))
