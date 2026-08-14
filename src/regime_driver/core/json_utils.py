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

    Phase-3 (W4 contract tolerance): a candidate that differs from valid JSON
    only by TRAILING COMMAS before `}`/`]` (a common model quirk) is repaired
    (string-safe) before being rejected.
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
                obj = _try_loads(candidate)
                if obj is not None:
                    return obj
    return None


def _try_loads(candidate: str) -> dict | None:
    """Parse a JSON candidate; tolerate a trailing-comma quirk (W4)."""
    try:
        obj = json.loads(candidate)
    except json.JSONDecodeError:
        obj = None
    if isinstance(obj, dict):
        return obj
    repaired = _strip_trailing_commas(candidate)
    if repaired != candidate:
        try:
            obj = json.loads(repaired)
        except json.JSONDecodeError:
            return None
        return obj if isinstance(obj, dict) else None
    return None


def _strip_trailing_commas(text: str) -> str:
    """Remove commas that sit OUTSIDE strings immediately before `}` or `]`.

    The model's trailing-comma quirk (`{"a":1,}`) is repaired string-safely so a
    value that merely contains `, }` in a string is never corrupted.
    """
    out = []
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            out.append(ch)
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
            out.append(ch)
        elif ch == ",":
            j = i + 1
            while j < len(text) and text[j] in " \t\n":
                j += 1
            if j < len(text) and text[j] in "}]":
                continue  # drop this trailing comma
            out.append(ch)
        else:
            out.append(ch)
    return "".join(out)
