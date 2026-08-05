"""Shared pure helpers for LLM-reply parsing (core, no I/O).

Centralizes logic that is otherwise duplicated across app modules: extracting a
JSON object from an LLM's free-text reply, and extracting the latest assistant
text from a message list.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def extract_json(text: str | None) -> dict | None:
    """Extract the first JSON object from a reply (handles fenced blocks)."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    m = _JSON_RE.search(text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None


def latest_assistant_text(messages: Sequence[object]) -> str:
    """The text of the newest assistant message, or '' if none.

    Accepts any sequence of objects exposing ``.role`` and ``.text`` (duck-typed
    so core stays free of infra imports).
    """
    for m in reversed(messages or []):
        role = getattr(m, "role", None)
        if role == "assistant":
            return getattr(m, "text", "") or ""
    return ""