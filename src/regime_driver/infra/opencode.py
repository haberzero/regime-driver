"""OpenCode server REST client (infra, stdlib urllib).

Provides a thin, typed wrapper over the opencode server HTTP API:
session create/read/abort, message send/read, and health check.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any


class OpenCodeError(Exception):
    """Raised for transport-level failures."""


@dataclass
class Message:
    """A single chat message."""

    role: str
    text: str
    ts: str | None = None
    error: str | None = None


@dataclass
class OpenCodeClient:
    """Thin typed client over the opencode server REST API."""

    base_url: str
    timeout: float = 240.0
    model: str | None = None

    # -- low-level ----------------------------------------------------------

    def _request(self, method: str, path: str, body: dict | None = None, timeout: float | None = None) -> Any:
        url = self.base_url + path
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            url,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            raise OpenCodeError(
                f"HTTP {e.code} on {method} {path}: {e.read().decode(errors='ignore')[:300]}"
            ) from e
        except Exception as e:  # URLError, timeout, etc.
            raise OpenCodeError(f"transport error on {method} {path}: {e}") from e

    # -- sessions -----------------------------------------------------------

    def create_session(self, title: str) -> str:
        res = self._request("POST", "/session", {"title": title})
        if not isinstance(res, dict) or not res.get("id"):
            raise OpenCodeError(f"create_session returned no id: {res}")
        return res["id"]

    def session_status(self, session_id: str) -> str | None:
        """Return the session's live status type ('busy'/'idle'/etc.).

        The busy/idle state lives in the global /session/status map, not in the
        session object. Returns None if the session is not in the map (e.g.
        idle/removed) or the map is unavailable.
        """
        res = self._request("GET", "/session/status", timeout=15.0)
        if not isinstance(res, dict):
            return None
        entry = res.get(session_id)
        if isinstance(entry, dict):
            return entry.get("type")
        return entry if isinstance(entry, str) else None

    def session_tokens(self, session_id: str) -> tuple[int, int]:
        """Return (reasoning, output) token counts for a session (0 if unknown)."""
        res = self._request("GET", f"/session/{session_id}", timeout=15.0)
        if not isinstance(res, dict):
            return 0, 0
        tokens = res.get("tokens") or {}
        return int(tokens.get("reasoning") or 0), int(tokens.get("output") or 0)

    def session_updated(self, session_id: str) -> float | None:
        """Return the session's last-updated epoch seconds, or None if unknown."""
        res = self._request("GET", f"/session/{session_id}", timeout=15.0)
        if not isinstance(res, dict):
            return None
        t = res.get("time") or {}
        updated = t.get("updated")
        if isinstance(updated, (int, float)):
            return float(updated) / 1000.0  # ms -> s
        return None

    def abort_session(self, session_id: str) -> None:
        self._request("POST", f"/session/{session_id}/abort", {}, timeout=15.0)

    # -- messages -----------------------------------------------------------

    def send_message(self, session_id: str, text: str, agent: str) -> None:
        body: dict = {"agent": agent, "parts": [{"type": "text", "text": text}]}
        if self.model:
            body["model"] = _model_obj(self.model)
        self._request("POST", f"/session/{session_id}/message", body)

    def ask_and_get_text(self, session_id: str, prompt: str, agent: str) -> str:
        """Send a prompt and synchronously return the assistant's text reply.

        Used for reviewer judgements (pure reasoning, POST returns the complete
        message). Raises OpenCodeError on transport failure or empty reply.
        """
        body: dict = {"agent": agent, "parts": [{"type": "text", "text": prompt}]}
        if self.model:
            body["model"] = _model_obj(self.model)
        res = self._request("POST", f"/session/{session_id}/message", body)
        if not isinstance(res, dict):
            raise OpenCodeError(f"ask_and_get_text: unexpected response: {res}")
        info = res.get("info") or {}
        if info.get("error"):
            raise OpenCodeError(f"ask_and_get_text: {info['error']}")
        text = "".join(
            p.get("text") or ""
            for p in res.get("parts") or []
            if p.get("type") in ("text", "reasoning")
        )
        if not text.strip():
            raise OpenCodeError("ask_and_get_text: empty reply")
        return text

    def read_messages(self, session_id: str) -> list[Message]:
        res = self._request("GET", f"/session/{session_id}/message", timeout=30.0)
        messages: list[Message] = []
        if not isinstance(res, list):
            return messages
        for m in res:
            info = m.get("info") or {}
            parts = m.get("parts") or []
            text = "".join(
                p.get("text") or ""
                for p in parts
                if p.get("type") in ("text", "reasoning")
            )
            t = info.get("time") or {}
            messages.append(
                Message(
                    role=info.get("role") or "?",
                    text=text,
                    ts=t.get("updated") or t.get("created"),
                    error=info.get("error"),
                )
            )
        return messages

    # -- health -------------------------------------------------------------

    def health(self) -> bool:
        try:
            res = self._request("GET", "/global/health", timeout=5.0)
            return bool(isinstance(res, dict) and res.get("healthy"))
        except OpenCodeError:
            return False


def _model_obj(model: str) -> dict:
    """'deepseek-api/deepseek-v4-flash' -> {'providerID','modelID'} (message
    endpoint requires the object form, not a string)."""
    if "/" in model:
        provider, _, model_id = model.partition("/")
        return {"providerID": provider, "modelID": model_id}
    return {"modelID": model}