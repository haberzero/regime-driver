"""Configurable offline mock of the opencode client interface.

Implements the same surface as ``regime_driver.infra.opencode.OpenCodeClient``
so it is a drop-in replacement for offline runs and tests:

    create_session / send_message / read_messages / session_status /
    session_tokens / abort_session / delete_session / ask_and_get_text / health

Behavior is deterministic + scriptable:

* **Default replies** (no script): a reviewer agent always advances to the first
  successor of the current node (needs ``sm``); a developer agent returns the
  ``worker_done`` marker (``[WORK_DONE]``). This alone drives a full flow to
  COMPLETE offline.
* **Per-(agent, node) rules** via ``rules``: an explicit reply, a simulated
  generation ``delay``, a ``stall`` (never completes -> watchdog STOP), or an
  ``error`` (a failed message). This is the fault-injection surface used to
  exercise timeout / stall / gate-error paths deterministically.
* **``send_message`` is run from the workflow's dispatch thread pool**, so a rule
  ``delay`` sleeps on that worker (parity with real streaming) while the mixed
  loop stays responsive — exactly like the live client.

The mock appends to ``self.msgs`` keyed by session id, so message history
*accumulates* like the real client (important: it does NOT replace, so the
stale-text judge bug the probe fixed is exercised faithfully).
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from ..infra.opencode import Message

_NODE_RE = re.compile(r"当前节点[:：]\s*(\w+)")


@dataclass
class MockRule:
    """One deterministic reply rule for an (agent[, node]) cell.

    ``reply``: explicit reply text. ``builder``: callable(node_id, text) -> str,
    mutually exclusive with ``reply``. ``delay``: simulated generation seconds
    (sleeps on the dispatch thread). ``stall``: never produce a completing reply
    (the watchdog's stall detection is the backstop). ``error``: emit a
    message carrying this error string.
    """

    reply: str | None = None
    builder: Callable[[str, str], str] | None = None
    delay: float = 0.0
    stall: bool = False
    error: str | None = None


_DEFAULT_RULE = MockRule()


class MockClient:
    """Scriptable, network-free implementation of the opencode client API."""

    def __init__(
        self,
        *,
        sm=None,
        rules: dict[tuple[str, str | None], MockRule] | None = None,
        worker_done: str = "[WORK_DONE]",
        tick: float = 0.001,
    ) -> None:
        self.sm = sm
        self.rules: dict[tuple[str, str | None], MockRule] = dict(rules or {})
        self.worker_done = worker_done
        self.tick = tick
        self.created = 0
        self.sid_title: dict[str, str] = {}
        self.msgs: dict[str, list[Message]] = {}
        self.sent: list[tuple[str, str, str]] = []
        self.aborted: list[str] = []

    # -- rules --------------------------------------------------------------

    def rule(self, agent: str, node: str | None = None, **kw) -> "MockClient":
        """Convenience: set a rule for (agent, node) and return self (chainable)."""
        self.rules[(agent, node)] = MockRule(**kw)
        return self

    def _rule_for(self, agent: str, node_id: str) -> MockRule:
        return self.rules.get((agent, node_id)) \
            or self.rules.get((agent, None)) \
            or _DEFAULT_RULE

    # -- node id parsing ----------------------------------------------------

    @staticmethod
    def node_of(text: str) -> str | None:
        m = _NODE_RE.search(text)
        return m.group(1) if m else None

    # -- OpenCodeClient-compatible surface ----------------------------------

    def create_session(self, title: str) -> str:
        self.created += 1
        sid = f"mock-{self.created}"
        self.sid_title[sid] = title
        self.msgs.setdefault(sid, [])
        return sid

    def session_status(self, session_id: str) -> str | None:
        return "busy" if self._is_stalled(session_id) else "idle"

    def session_tokens(self, session_id: str) -> tuple[int, int]:
        return (0, 0)

    def abort_session(self, session_id: str) -> None:
        self.aborted.append(session_id)

    def delete_session(self, session_id: str) -> None:
        self.msgs.pop(session_id, None)

    def health(self) -> bool:
        return True

    def send_message(self, session_id: str, text: str, agent: str) -> None:
        node_id = self.node_of(text) or ""
        rule = self._rule_for(agent, node_id)
        self.sent.append((session_id, text, agent))
        if rule.delay:
            time.sleep(rule.delay)
        if rule.stall:
            # mark the session as persistently busy; never append a completing reply
            self.msgs.setdefault(session_id, []).append(
                Message(id=f"m-{len(self.msgs.get(session_id, []))}", role="assistant",
                        text="thinking endlessly...", ts=str(time.time())))
            return
        if rule.error:
            self.msgs.setdefault(session_id, []).append(
                Message(id=f"m-{len(self.msgs.get(session_id, []))}", role="assistant",
                        text="", error=rule.error, ts=str(time.time())))
            return
        reply = rule.reply if rule.reply is not None else (
            rule.builder(node_id, text) if rule.builder else self._default_reply(agent, node_id))
        self.msgs.setdefault(session_id, []).append(
            Message(id=f"m-{len(self.msgs.get(session_id, []))}", role="assistant",
                    text=reply, reply=reply, completed=str(time.time()), ts=str(time.time())))

    def _default_reply(self, agent: str, node_id: str) -> str:
        if agent == "reviewer":
            return json.dumps(self._default_verdict(node_id))
        # developer / any other agent: report + [WORK_DONE]
        return f"已完成节点 {node_id}\n{self.worker_done}"

    def _default_verdict(self, node_id: str) -> dict:
        target = None
        if self.sm is not None:
            succ = self.sm.successors(node_id)
            if succ:
                target = sorted(succ)[0]
        return {"node": node_id, "verdict": "advance", "action": "advance",
                "next_state": target, "confidence": 0.9, "reason": "mock advance"}

    def read_messages(self, session_id: str) -> list[Message]:
        return list(self.msgs.get(session_id, []))

    def ask_and_get_text(self, session_id, prompt, agent, model=None) -> str:
        self.send_message(session_id, prompt, agent)
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            msgs = self.read_messages(session_id)
            for m in reversed(msgs):
                if m.role == "assistant":
                    if m.error:
                        raise RuntimeError(f"ask_and_get_text: {m.error}")
                    if (m.reply or m.text).strip():
                        return m.reply or m.text
            time.sleep(self.tick)
        raise TimeoutError("ask_and_get_text: no reply")

    # -- stall bookkeeping ----------------------------------------------------

    def _is_stalled(self, session_id: str) -> bool:
        """A session is 'busy' if its latest message was a stall (no completion)."""
        for m in reversed(self.msgs.get(session_id, [])):
            if m.role == "assistant":
                return m.completed is None
        return False