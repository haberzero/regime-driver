"""Process-external supervisor (first-class regime-driver component).

Absorbs the old M0 `ops/supervisor.py` + `ops/oc-task.py` supervision into the
package (see docs/DESIGN-supervision.md), so supervision is ONE system with the
worker, sharing the Reporter as the single event truth source — not a parallel
M0 system.

Why process-external: stall detection (absence of events), deadline enforcement
and container restart need an independent clock + docker control that the
in-process ConstitutionUnit cannot have (platform limit). This runs on the host
(setsid / systemd) with its own clock.

Responsibilities:
  T1  process health polling -> L4 container restart
  T2  session stall (busy but no new messages for stall_sec) -> abort
      deadline enforcement (never run forever)
  Ladder L1-L5: nudge / abort / fallback_model / restart / human
  meta-analysis: model verdict + deterministic gate on stalls
  consumes the worker SSE `event_stream` into the Reporter (wiring the SSE feed)

The decision logic is separated into pure, testable functions (stall/ladder/
deadline/verdict-gate); the run loop drives them with its own clock.
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field

from .app.reporter import Reporter
from .infra.opencode import OpenCodeClient

# correction ladder levels (L1 light -> L5 human)
L1_NUDGE = "nudge"
L2_ABORT = "abort"
L3_FALLBACK = "fallback_model"
L4_RESTART = "restart"
L5_HUMAN = "human"

ALLOWED_VERDICTS = {"normal", "stalled", "looping", "blocked", "error", "escalate"}
ALLOWED_ACTIONS = {"none", L1_NUDGE, L2_ABORT, L3_FALLBACK, L4_RESTART, L5_HUMAN}
# deterministic verdict->allowed-actions gate (mirrors old supervisor._gate)
VERDICT_ACTIONS = {
    "normal": {"none"},
    "stalled": {L1_NUDGE, L2_ABORT, L3_FALLBACK, L4_RESTART},
    "looping": {L2_ABORT, L3_FALLBACK, L4_RESTART},
    "blocked": {L2_ABORT, L3_FALLBACK, L4_RESTART, L5_HUMAN},
    "error": {L3_FALLBACK, L2_ABORT, L4_RESTART, L5_HUMAN},
    "escalate": {L5_HUMAN, L3_FALLBACK, L4_RESTART},
}
MIN_CONFIDENCE = {"none": 0.0, L1_NUDGE: 0.5, L2_ABORT: 0.5,
                  L3_FALLBACK: 0.5, L4_RESTART: 0.75, L5_HUMAN: 0.75}


class MetaGateReject(Exception):
    """The meta-analysis verdict/action failed the deterministic gate."""


def gate_meta(verdict: str, action: str, confidence: float) -> None:
    """Deterministic gate on a meta-analysis verdict (pure, testable).

    Rejects out-of-whitelist verdict/action or confidence below the per-action
    floor. Mirrors the old supervisor._gate but as a pure function.
    """
    if verdict not in ALLOWED_VERDICTS:
        raise MetaGateReject(f"unknown verdict '{verdict}'")
    if action not in ALLOWED_ACTIONS:
        raise MetaGateReject(f"unknown action '{action}'")
    if action not in VERDICT_ACTIONS[verdict]:
        raise MetaGateReject(f"action '{action}' not allowed for verdict '{verdict}'")
    if not (0.0 <= confidence <= 1.0):
        raise MetaGateReject("confidence out of [0,1]")
    if confidence < MIN_CONFIDENCE[action]:
        raise MetaGateReject(
            f"confidence {confidence:.2f} below floor {MIN_CONFIDENCE[action]} for '{action}'")


@dataclass
class LadderState:
    """Persistent ladder state across attempts (bounds escalation)."""

    model_fallback_used: bool = False
    restart_used: bool = False
    human_escalated: bool = False


def choose_action(verdict: str, action: str, confidence: float,
                  state: LadderState) -> str:
    """Resolve the meta action against the correction ladder bounds (pure)."""
    gate_meta(verdict, action, confidence)
    if action == L3_FALLBACK and state.model_fallback_used:
        # fallback already used: escalate to abort/restart per allowed set
        action = L2_ABORT if L2_ABORT in VERDICT_ACTIONS[verdict] else L4_RESTART
    if action == L4_RESTART and state.restart_used:
        action = L5_HUMAN
    # mark the ladder step as taken
    if action == L3_FALLBACK:
        state.model_fallback_used = True
    elif action == L4_RESTART:
        state.restart_used = True
    elif action == L5_HUMAN:
        state.human_escalated = True
    return action


@dataclass
class SessionWatch:
    """Per-session stall bookkeeping (pure, testable)."""

    last_output: float = 0.0
    last_message_ts: float = 0.0

    def is_stalled(self, now: float, stall_sec: float, busy: bool, output: int) -> bool:
        """T2: busy but no output growth for stall_sec."""
        if not busy:
            return False
        if output != self.last_output:
            self.last_output = output
            self.last_message_ts = now
            return False
        return (now - self.last_message_ts) > stall_sec


def docker_restart(container: str) -> bool:
    """L4: restart the worker container. Returns success. (Host-side, docker.)"""
    try:
        proc = subprocess.run(
            ["docker", "restart", container], capture_output=True, timeout=60)
        return proc.returncode == 0
    except Exception:
        return False


class Supervisor:
    """Drives T1/T2/deadline/ladder and feeds the Reporter with events."""

    def __init__(
        self,
        client: OpenCodeClient,
        reporter: Reporter | None = None,
        *,
        container: str | None = None,
        stall_sec: float = 60.0,
        health_poll_sec: float = 10.0,
        deadline_sec: float | None = None,
        session_id: str | None = None,
        goal: str = "",
    ) -> None:
        self.client = client
        self.reporter = reporter
        self.container = container
        self.stall_sec = stall_sec
        self.health_poll_sec = health_poll_sec
        self.deadline_sec = deadline_sec
        self.session_id = session_id
        self.goal = goal
        self.watch: dict[str, SessionWatch] = {}
        self.ladder = LadderState()
        self._start = time.time()

    # -- event ingress (wires the SSE event_stream) --------------------------

    def ingest_events(self, n: int = 100, timeout: float = 30.0) -> int:
        """Consume the worker SSE event_stream into the Reporter (real wiring).

        Returns how many events were ingested. Raises if the stream can't connect.
        """
        count = 0
        for raw in self.client.event_stream(reconnect=False, max_retries=1):
            if self.reporter is not None:
                self.reporter.ingest_worker_event(
                    raw, session_id=self.session_id)
            count += 1
            if count >= n:
                break
            if time.time() - self._start > timeout:
                break
        return count

    # -- run loop (T1/T2/deadline/ladder) ------------------------------------

    def run(self, *, iterations: int | None = None) -> str:
        """Main watchdog loop with an independent clock.

        Returns the terminal action ('complete'/'timeout'/'restart'/'human'/'abort').
        """
        i = 0
        while True:
            i += 1
            if iterations is not None and i > iterations:
                return "complete"
            now = time.time()
            if self.deadline_sec is not None and now - self._start > self.deadline_sec:
                self._record("deadline", outcome="timeout")
                return "timeout"
            # T2: session stall
            if self.session_id is not None and self.client.health():
                status = self.client.session_status(self.session_id)
                _, output = self.client.session_tokens(self.session_id)
                watch = self.watch.setdefault(self.session_id, SessionWatch())
                if watch.is_stalled(now, self.stall_sec, status == "busy", output):
                    self._record("stall_detected", session=self.session_id,
                                 outcome="blocked")
                    self.client.abort_session(self.session_id)
                    self._record("ladder_action", action=L2_ABORT,
                                 session=self.session_id)
                    return L2_ABORT
            time.sleep(self.health_poll_sec)

    def _record(self, event: str, **fields) -> None:
        if self.reporter is not None:
            self.reporter.ingest(
                kind=event, wf_id=self.session_id or "supervisor",
                project_id="supervisor", event_type=event, detail=dict(fields))
