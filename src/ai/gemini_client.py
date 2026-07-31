"""
Shared Gemini client for the whole app.

Why this exists: the one-liner pattern `genai.Client().models.generate_content(...)`
creates an anonymous client that nothing holds a reference to. Under
Streamlit, Python may garbage-collect it (closing the underlying HTTP
transport) between reruns or even mid-call, producing:

    Cannot send a request, as the client has been closed.

Fix: ONE module-level client, created lazily, held for the process
lifetime, and transparently recreated if it ever reports being closed.
All Gemini calls in the project should go through generate() below.

Requires GEMINI_API_KEY in the environment (.env is loaded here too, so
callers don't have to remember).
"""
from __future__ import annotations

import os

from dotenv import load_dotenv
load_dotenv()

_client = None

# The model every caller falls back to when GEMINI_MODEL is unset.
#
# Defined ONCE and imported, because the previous three private copies drifted:
# they all still said "gemini-2.5-flash" long after the project had moved on.
# That generation was retired for new users mid-project (see Results.md), so a
# newcomer who set only GEMINI_API_KEY got a model that may no longer exist —
# and the measured numbers in Results.md were produced with the model below,
# not with the old fallback.
DEFAULT_MODEL = "gemini-3.1-flash-lite"


def resolve_model(model: str | None = None) -> str:
    """Caller's explicit choice, else GEMINI_MODEL, else DEFAULT_MODEL."""
    return model or os.getenv("GEMINI_MODEL") or DEFAULT_MODEL


def _new_client():
    from google import genai
    return genai.Client()              # reads GEMINI_API_KEY from env


def get_client():
    global _client
    if _client is None:
        _client = _new_client()
    return _client


def generate(contents, model: str | None = None, config=None):
    """generate_content through the shared client, with one automatic
    recreate-and-retry if the client turns out to be closed."""
    global _client
    kwargs = {"model": resolve_model(model), "contents": contents}
    if config is not None:
        kwargs["config"] = config
    try:
        return get_client().models.generate_content(**kwargs)
    except Exception as e:                                  # noqa: BLE001
        if "closed" in str(e).lower():
            _client = _new_client()
            return _client.models.generate_content(**kwargs)
        raise