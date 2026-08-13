"""Shared pure helpers for LLM-reply parsing (core, no I/O).

Centralizes logic that is otherwise duplicated across app modules: extracting a
JSON object from an LLM's free-text reply.
"""

from __future__ import annotations

import json
import re


def extract_json(text: str | None) -> dict | None:
    """Extract the first complete, balanced JSON OBJECT from a reply.

    Robust against prose around the JSON (the reviewer occasionally writes
    analysis before/after the object) and against fenced blocks. Walks braces
    tracking string state so it does not break on braces inside strings, and
    returns the first object that actually parses as a dict. A truncated object
    (token-limit cut) is skipped, not misparsed.
    """
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    start = -1
    depth = 0
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if start < 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0:
                depth = 0  # stray '}' in prose before any '{' — do not poison state
            if depth == 0 and start >= 0:
                candidate = text[start:i + 1]
                start = -1
                try:
                    obj = json.loads(candidate)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    return obj
    return None
