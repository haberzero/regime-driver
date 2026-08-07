"""OpenCode server REST client (infra, stdlib urllib).

Provides a thin, typed wrapper over the opencode server HTTP API:
session create/read/abort, message send/read, and health check.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


class OpenCodeError(Exception):
    """Raised for transport-level failures."""


@dataclass
class Message:
    """A single chat message."""

    id: str
    role: str
    text: str
    ts: str | None = None
    error: str | None = None
    completed: str | None = None   # info.time.completed (turn-finished timestamp)
    finish: str | None = None      # info.finish (e.g. 'stop', '' on error)
    reply: str = ""                # text-parts only (developer's final reply, no reasoning)


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

    def session_status_map(self) -> dict[str, str | None]:
        """Return the full {session_id: status_type} map from /session/status."""
        res = self._request("GET", "/session/status", timeout=15.0)
        if not isinstance(res, dict):
            return {}
        out: dict[str, str | None] = {}
        for sid, entry in res.items():
            if isinstance(entry, dict):
                out[sid] = entry.get("type")
            elif isinstance(entry, str):
                out[sid] = entry
            else:
                out[sid] = None
        return out

    def list_sessions(self) -> list[dict]:
        """Return the full list of sessions from GET /session (id/title/tokens/...)."""
        res = self._request("GET", "/session", timeout=15.0)
        if not isinstance(res, list):
            return []
        return [s for s in res if isinstance(s, dict)]

    def session_tokens(self, session_id: str) -> tuple[int, int]:
        """Return (reasoning, output) token counts for a session (0 if unknown)."""
        res = self._request("GET", f"/session/{session_id}", timeout=15.0)
        if not isinstance(res, dict):
            return 0, 0
        tokens = res.get("tokens") or {}
        return int(tokens.get("reasoning") or 0), int(tokens.get("output") or 0)

    def abort_session(self, session_id: str) -> None:
        self._request("POST", f"/session/{session_id}/abort", {}, timeout=15.0)

    def delete_session(self, session_id: str) -> None:
        self._request("DELETE", f"/session/{session_id}", timeout=15.0)

    # -- messages -----------------------------------------------------------

    def send_message(self, session_id: str, text: str, agent: str) -> None:
        body: dict = {"agent": agent, "parts": [{"type": "text", "text": text}]}
        if self.model:
            body["model"] = _model_obj(self.model)
        self._request("POST", f"/session/{session_id}/message", body)

    def ask_and_get_text(self, session_id: str, prompt: str, agent: str, model: str | None = None) -> str:
        """Send a prompt and wait for the assistant's complete text reply.

        opencode's POST /message is asynchronous/streaming: the POST returns
        before the model finishes. This polls until a NEW assistant message
        (with text) appears after the prompt, so the reply is complete and
        reliable. Raises OpenCodeError on transport failure, reply error, or
        timeout.
        """
        base_count = len(self.read_messages(session_id))
        body: dict = {"agent": agent, "parts": [{"type": "text", "text": prompt}]}
        if model or self.model:
            body["model"] = _model_obj(model or self.model)
        # POST /message is a streaming request: it stays open until the model's
        # turn completes. Use the full timeout so a long reviewer judgement is
        # not cut off at 30s.
        self._request("POST", f"/session/{session_id}/message", body, timeout=self.timeout)

        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            messages = self.read_messages(session_id)
            if len(messages) <= base_count:
                time.sleep(1.0)
                continue  # no new message yet
            # a new message appeared; return the newest assistant text if non-empty
            for m in reversed(messages):
                if m.role != "assistant":
                    continue
                if m.error:
                    raise OpenCodeError(f"ask_and_get_text: {m.error}")
                if m.text.strip():
                    return m.text
                break  # newest assistant message is empty; keep polling
            time.sleep(1.0)
        raise OpenCodeError("ask_and_get_text: timed out waiting for reply")

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
            reply = "".join(
                p.get("text") or ""
                for p in parts
                if p.get("type") == "text"
            )
            ie = info.get("error")
            error = ie.get("message") if isinstance(ie, dict) else (ie or None)
            t = info.get("time") or {}
            messages.append(
                Message(
                    id=str(info.get("id") or ""),
                    role=info.get("role") or "?",
                    text=text,
                    ts=t.get("updated") or t.get("created"),
                    error=error,
                    completed=t.get("completed"),
                    finish=info.get("finish"),
                    reply=reply,
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