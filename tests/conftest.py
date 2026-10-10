"""Tests cover free_llm.py only (basesolanascan.py installs packages and starts work at import).
External network access is blocked; providers are replaced with in-memory fakes."""
import os
import socket
import sys
from pathlib import Path

for k in list(os.environ):
    if k.endswith("_API_KEY") or k.startswith(("FREE_LLM", "TELEGRAM", "OPENAI")):
        os.environ.pop(k, None)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

_real_connect = socket.socket.connect
_LOOPBACK = {"127.0.0.1", "::1", "localhost"}


def _guarded_connect(self, address, *args, **kwargs):
    # asyncio on Windows builds its event loop on a loopback socket pair; allow only that.
    host = address[0] if isinstance(address, tuple) else address
    if host not in _LOOPBACK:
        raise RuntimeError("Network access is blocked in tests")
    return _real_connect(self, address, *args, **kwargs)


def _blocked(*args, **kwargs):
    raise RuntimeError("Network access is blocked in tests")


socket.socket.connect = _guarded_connect
socket.create_connection = _blocked
