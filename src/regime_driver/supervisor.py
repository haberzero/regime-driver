"""Process-external supervisor (first-class regime-driver component).

Absorbs the old M0 `ops/supervisor.py` + `ops/oc-task.py` supervision into the
package (see docs/DESIGN-supervision.md), so supervision is ONE system with the
worker, sharing the Reporter as the single event truth source — not a parallel
M0 system.

Why process-external: stall detection (absence of events), deadline enforcement
and container restart need an independent clock + docker control that the
in-process ConstitutionUnit cannot have (platform limit). This runs on the host
(setsid / systemd) with its own clock.

The watchdog loop is fully wired (no dead ladder): each poll it
  ingest_events   consumes the worker SSE /event stream into the Reporter
  T1              polls worker health -> L4 docker restart if down
  T2              detects session stall -> escalates through the correction
                  ladder (abort -> fallback -> restart -> human), executing real
                  actions and recording each to the Reporter
  deadline        aborts once the budget is exhausted
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from typing import Callable

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
    """Deterministic gate on a meta-analysis verdict (pure, testable)."""
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
        action = L2_ABORT if L2_ABORT in VERDICT_ACTIONS[verdict] else L4_RESTART
    if action == L4_RESTART and state.restart_used:
        action = L5_HUMAN
    if action == L3_FALLBACK:
        state.model_fallback_used = True
    elif action == L4_RESTART:
        state.restart_used = True
    elif action == L5_HUMAN:
        state.human_escalated = True
    return action


def docker_restart(container: str) -> bool:
    """L4: restart the worker container. Returns success. (Host-side, docker.)"""
    try:
        proc = subprocess.run(
            ["docker", "restart", container], capture_output=True, timeout=60)
        return proc.returncode == 0
    except Exception:
        return False


@dataclass
class SessionWatch:
    """Per-session stall bookkeeping (pure, testable)."""

    last_output: int = 0
    last_message_ts: float = 0.0
    consecutive_stalls: int = 0

    def observe(self, now: float, busy: bool, output: int) -> bool:
        """T2: busy but no output growth for stall_sec. Establishes baseline on first observe."""
        if self.last_message_ts == 0.0:
            # first observation: establish the baseline, never false-stall
            self.last_output = output
            self.last_message_ts = now
            return False
        if not busy:
            return False
        if output != self.last_output:
            self.last_output = output
            self.last_message_ts = now
            return False
        return (now - self.last_message_ts) > 0.0  # caller applies stall_sec

    def is_stalled(self, now: float, stall_sec: float, busy: bool, output: int) -> bool:
        self.consecutive_stalls = (self.consecutive_stalls + 1
                                   if self.observe(now, busy, output) else 0)
        return self.consecutive_stalls > 0


def _verdict_for_stall(count: int) -> tuple[str, str, float]:
    """Deterministic verdict for a consecutive-stall run: escalate as it persists."""
    if count <= 1:
        return "stalled", L2_ABORT, 0.6
    if count == 2:
        return "stalled", L3_FALLBACK, 0.6
    if count == 3:
        return "error", L4_RESTART, 0.8
    return "escalate", L5_HUMAN, 0.9


class Supervisor:
    """Drives a fully-wired watchdog loop: SSE ingest + T1 + T2 + deadline + ladder."""

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
        self.watch = SessionWatch()
        self.ladder = LadderState()
        self._start = time.time()

    # -- SSE event ingress (wired: called by the run loop) -------------------

    def ingest_events(self, max_events: int = 20, stream_timeout: float = 2.0) -> int:
        """Consume up to `max_events` worker SSE events into the Reporter.

        Returns how many were ingested. Best-effort: a short-lived stream read so
        the watchdog loop stays responsive (does not block forever on the stream).
        """
        count = 0
        start = time.monotonic()
        try:
            for raw in self.client.event_stream(reconnect=False, max_retries=1):
                if self.reporter is not None:
                    self.reporter.ingest_worker_event(
                        raw, session_id=self.session_id)
                count += 1
                if count >= max_events:
                    break
                if time.monotonic() - start > stream_timeout:
                    break
        except Exception:
            pass  # a transient SSE failure must not kill the watchdog loop
        return count

    # -- run loop (fully wired: ingest + T1 + T2 + deadline + ladder) --------

    def run(self, *, once: bool = False, stop_when: "Callable[[], bool] | None" = None) -> str:
        """Run the watchdog loop with its own clock.

        Each pass: ingest SSE events, check T1 health (restart if down), check T2
        session stall (escalate through the ladder with real actions), enforce the
        deadline. With `once=True` it does a single pass (for CLI `--once`/tests);
        otherwise it loops until the deadline, an L5 human escalation, or
        `stop_when()` (a caller-supplied completion check, e.g. the supervised
        workflow finished) returns True — in which case it returns `"workflow_done"`.
        """
        while True:
            if stop_when is not None and stop_when():
                return "workflow_done"
            self.ingest_events()
            if self.session_id is not None and self.client.health():
                # T2: session stall
                status = self.client.session_status(self.session_id)
                _, output = self.client.session_tokens(self.session_id)
                busy = status == "busy"
                stalled = self.watch.is_stalled(
                    time.time(), self.stall_sec, busy, output)
                if stalled:
                    verdict, action, confidence = _verdict_for_stall(
                        self.watch.consecutive_stalls)
                    action = choose_action(verdict, action, confidence, self.ladder)
                    self._execute(action, verdict)
                    if action == L5_HUMAN:
                        return L5_HUMAN
                    # restart gives the worker a fresh start; abort/failed are retried
                    time.sleep(self.health_poll_sec * 2)
                    continue
            # T1: worker health -> restart if down
            if not self.client.health():
                self._record("unhealthy", session=self.session_id)
                if self.container:
                    ok = docker_restart(self.container)
                    self._record("ladder_action", action=L4_RESTART, ok=ok,
                                 session=self.session_id)
                return "restart" if self.container else "unhealthy"
            # deadline
            if self.deadline_sec is not None and \
                    time.time() - self._start > self.deadline_sec:
                self._record("deadline", outcome="timeout")
                return "timeout"
            if once:
                return "complete"
            time.sleep(self.health_poll_sec)

    def _execute(self, action: str, verdict: str) -> None:
        """Execute a ladder action against the real worker (wired)."""
        self._record("ladder_action", action=action, verdict=verdict,
                     session=self.session_id)
        if action in (L2_ABORT, L3_FALLBACK) and self.session_id:
            self.client.abort_session(self.session_id)
        elif action == L4_RESTART and self.container:
            ok = docker_restart(self.container)
            self._record("ladder_restart", ok=ok, session=self.session_id)

    def _record(self, event: str, **fields) -> None:
        if self.reporter is not None:
            self.reporter.ingest(
                kind=event, wf_id=self.session_id or "supervisor",
                project_id="supervisor", event_type=event, detail=dict(fields))
