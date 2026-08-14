"""Process-external supervisor (first-class regime-driver component).

Absorbs the old M0 `ops/supervisor.py` + `ops/oc-task.py` supervision into the
package (see docs/DESIGN-supervision.md), so supervision is ONE system with the
worker, sharing the Reporter as the single event truth source — not a parallel
M0 system.

Why process-external: stall detection (absence of events), deadline enforcement
and container restart need an independent clock + docker control that the
in-process WatchdogUnit cannot have (platform limit). This runs on the host
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

import json
import re
import subprocess
import time
from dataclasses import dataclass
from typing import Callable

from .app.reporter import Reporter
from .app.sse_activity import is_progress_event
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
    """L4: restart the worker container. Returns success. (Host-side, docker.)

    Handles the common host where the invoking shell is in a pre-docker-group
    session: tries plain `docker`, then falls back to `sg docker -c` (the wrapper
    required when the shell's group list is stale).
    """
    candidates = [
        ["docker", "restart", container],
        ["sg", "docker", "-c", f"docker restart {container}"],
    ]
    for cmd in candidates:
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=60)
            if proc.returncode == 0:
                return True
        except Exception:
            continue
    return False


@dataclass
class SessionWatch:
    """Per-session stall bookkeeping (pure, testable).

    T2 semantics (WORK_PLAN10): a session is STALLED only if it has been busy
    AND produced no SSE progress for a *contiguous* window of at least
    ``stall_sec`` seconds. Liveness is measured by the SSE-activity timestamp
    (``activity_ts``) fed in from ``Supervisor.ingest_events`` — token counts
    are deliberately NOT used because opencode persists them only at
    step-finish (stale during long single-step generations).

    ``last_message_ts`` = last time we saw any SSE progress.
    ``_stalled_since`` = start of the current frozen window (0 = none).
    ``consecutive_stalls`` counts contiguous windows that each exceeded
    stall_sec, driving the deterministic correction ladder one rung per window.
    """

    last_message_ts: float = 0.0
    consecutive_stalls: int = 0
    _stalled_since: float = 0.0

    def observe(self, now: float, busy: bool, activity_ts: float = 0.0) -> bool:
        """Update bookkeeping from one poll observation (pure state updater).

        Returns True when the session recovered (SSE activity resumed / went
        idle) — used by ``is_stalled`` to reset the consecutive escalation
        counter so a stall episode is counted only while it persists.
        """
        recovered = False
        if activity_ts and activity_ts > self.last_message_ts:
            # SSE streaming activity counts as progress (long deep-reasoning
            # phases stream message.part.delta continuously).
            self.last_message_ts = activity_ts
            self._stalled_since = 0.0
            recovered = True
        if self.last_message_ts == 0.0:
            # first observation: establish the baseline, never false-stall
            self.last_message_ts = now
            self._stalled_since = 0.0
            return recovered
        if not busy:
            # not busy -> no stall possible; reset so a later busy window starts
            # from a fresh baseline
            self.last_message_ts = now
            self._stalled_since = 0.0
            return True
        if self._stalled_since == 0.0:
            # frozen: anchor the window at the last progress time
            self._stalled_since = self.last_message_ts
        return recovered

    def is_stalled(self, now: float, stall_sec: float, busy: bool,
                   activity_ts: float = 0.0) -> bool:
        """True once the session has been frozen-and-busy for >= stall_sec.

        The window is anchored at the last progress time (``last_message_ts`` /
        ``_stalled_since``), so a session silent for ``stall_sec`` fires. Returns
        True once per expired window (then advances the anchor to consume it),
        so continued frozen escalates the ladder one rung per stall_sec. A
        recovery (SSE activity resumed / idle) resets the consecutive counter so
        escalation does not leak across separate episodes.
        """
        recovered = self.observe(now, busy, activity_ts=activity_ts)
        if recovered:
            self.consecutive_stalls = 0
            return False
        if self._stalled_since and now - self._stalled_since >= stall_sec:
            self.consecutive_stalls += 1
            # consume this window: re-fire only after another stall_sec of silence
            self._stalled_since = now
            return True
        return False


def _verdict_for_stall(count: int) -> tuple[str, str, float]:
    """Deterministic verdict for a consecutive-stall run: escalate as it persists."""
    if count <= 1:
        return "stalled", L2_ABORT, 0.6
    if count == 2:
        return "stalled", L3_FALLBACK, 0.6
    if count == 3:
        return "error", L4_RESTART, 0.8
    return "escalate", L5_HUMAN, 0.9


# -- intelligent meta-analysis (real model judges verdict, deterministic-gated) --

_META_SYSTEM = (
    "You are the independent meta-reviewer of an institutional-process robot. "
    "A worker session appears stalled (busy but producing no new output). "
    "Judge the situation from the goal, the deadline, and the session's recent "
    "messages, and reply with STRICT JSON only (no prose, no markdown):\n"
    '{"verdict":"normal|stalled|looping|blocked|error|escalate",'
    '"confidence":0.0,"recommended_action":"none|nudge|abort|fallback_model|restart|human",'
    '"reason":"1-2 sentences"}\n'
    "Rules: verdict 'normal' => action 'none'. A genuinely stuck/looping session "
    "=> 'looping' with abort/fallback_model. A hard block needing a human => "
    "'blocked'/'escalate' with human. Never fabricate; use the evidence."
)


def _parse_meta_verdict(reply: str) -> dict:
    """Parse the strict-JSON meta verdict from a model reply (pure, testable).

    Raises ValueError if no usable JSON object is found.
    """
    text = reply.strip()
    # tolerate surrounding prose/markdown fences by extracting the first {...}
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        raise ValueError(f"no JSON object in meta reply: {text[:200]!r}")
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        raise ValueError(f"meta reply JSON invalid: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError("meta reply is not a JSON object")
    for key in ("verdict", "recommended_action", "confidence"):
        if key not in data:
            raise ValueError(f"meta reply missing '{key}'")
    return data


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
        meta_enabled: bool = False,
        meta_model: str | None = None,
        agent_reviewer: str = "reviewer",
        meta_max_context_msgs: int = 20,
    ) -> None:
        self.client = client
        self.reporter = reporter
        self.container = container
        self.stall_sec = stall_sec
        self.health_poll_sec = health_poll_sec
        self.deadline_sec = deadline_sec
        self.session_id = session_id
        self.goal = goal
        self.meta_enabled = meta_enabled
        self.meta_model = meta_model
        self.agent_reviewer = agent_reviewer
        self.meta_max_context_msgs = meta_max_context_msgs
        self.watch = SessionWatch()
        self.ladder = LadderState()
        self._start = time.time()
        self._meta_sid: str | None = None
        self._last_activity_ts: float = 0.0
        self._events_no_type = 0          # events whose type could not be resolved
        self._last_liveness_log = 0.0     # throttle liveness warnings
        # drive-mode meta channel: only review watchdog fires recorded AFTER this
        # supervisor started (avoids replaying the whole pre-existing journal).
        self._last_meta_fire_ts: float = self._start

    # -- SSE event ingress (wired: called by the run loop) -------------------

    def ingest_events(self, max_events: int = 20, stream_timeout: float = 2.0) -> int:
        """Consume up to `max_events` worker SSE events into the Reporter.

        Returns how many were ingested. Best-effort: a short-lived stream read so
        the watchdog loop stays responsive (does not block forever on the stream).

        Genuine progress events (message deltas / completed / session transitions)
        update ``_last_activity_ts`` for T2; the per-poll ``server.connected``
        handshake does NOT — otherwise every poll would look like session
        activity and T2 stall detection would never fire.
        """
        count = 0
        start = time.monotonic()
        try:
            for raw in self.client.event_stream(reconnect=False, max_retries=1):
                etype = raw.get("event")
                if etype is None and raw.get("data") not in (None, {}):
                    # unresolved event type (no `event:` line AND no `data.type`,
                    # and non-empty payload): consumers (T2 liveness / reporter
                    # delta-drop) would silently degrade. Count + throttle a
                    # warning so the loss is visible. Empty heartbeats (`data: {}`)
                    # are skipped — they carry no type by design.
                    self._events_no_type += 1
                    now = time.time()
                    if now - self._last_liveness_log >= 60.0:
                        self._last_liveness_log = now
                        self._safe_record(
                            "sse_type_unresolved",
                            count=self._events_no_type,
                            session=self.session_id,
                        )
                if self.reporter is not None:
                    self.reporter.ingest_worker_event(
                        raw, session_id=self.session_id)
                if is_progress_event(etype):
                    self._last_activity_ts = time.time()
                count += 1
                if time.monotonic() - start > stream_timeout:
                    break
                if count >= max_events:
                    break
        except Exception as exc:
            # a transient SSE failure must not kill the watchdog loop, but it
            # must be visible (audit) rather than silently swallowed.
            self._safe_record("sse_error", err=str(exc), session=self.session_id)
        return count

    def _safe_record(self, event: str, **fields) -> None:
        """Record an audit event but never raise — a logging/journal failure on
        the error path must not kill the watchdog loop it is meant to protect."""
        try:
            self._record(event, **fields)
        except Exception:
            pass

    # -- intelligent meta-analysis (real model judges the verdict) ------------

    def _session_context(self, max_msgs: int,
                         session_id: str | None = None) -> str:
        """Render recent messages of a supervised session as analysis evidence."""
        target = session_id or self.session_id
        try:
            msgs = self.client.read_messages(target)
        except Exception as exc:
            self._record("meta_error", err=str(exc))
            return "(could not read session messages)"
        lines = []
        for m in msgs[-max_msgs:]:
            role = m.role or "?"
            text = (m.reply or m.text or "").strip()
            if text:
                lines.append(f"[{role}] {text[:400]}")
        return "\n".join(lines[-max_msgs:]) or "(no messages)"

    def meta_analyze(self, session_id: str | None = None) -> tuple[str, str, float] | None:
        """Ask an independent model to judge the stall; return a gated verdict.

        `session_id` overrides the supervised session (drive mode: reviews the
        session a watchdog fire was attributed to, which may have rotated away
        from the anchor). Returns ``(verdict, action, confidence)`` only if the
        model reply parses to strict JSON AND passes the deterministic gate;
        otherwise records the failure and returns None (the caller falls back to
        the deterministic ladder). This is the real-model rung kept honest by
        ``gate_meta``.
        """
        target = session_id or self.session_id
        if target is None or not self.meta_enabled:
            return None
        if self._meta_sid is None:
            try:
                self._meta_sid = self.client.create_session("regime-meta")
            except Exception as exc:
                self._record("meta_error", err=f"create session: {exc}")
                return None
        context = self._session_context(self.meta_max_context_msgs, target)
        prompt = (
            f"{_META_SYSTEM}\n\n"
            f"GOAL: {self.goal or '(not provided)'}\n"
            f"DEADLINE_SEC: {self.deadline_sec}\n"
            f"SESSION: {target}\n"
            f"RECENT MESSAGES:\n{context}\n\n"
            "Verdict JSON:"
        )
        try:
            reply = self.client.ask_and_get_text(
                self._meta_sid, prompt, self.agent_reviewer, model=self.meta_model)
        except Exception as exc:
            self._record("meta_error", err=str(exc))
            return None
        try:
            data = _parse_meta_verdict(reply)
            verdict = str(data["verdict"])
            action = str(data["recommended_action"])
            confidence = float(data["confidence"])
        except (ValueError, TypeError) as exc:
            self._record("meta_error", err=f"parse: {exc}")
            return None
        try:
            gate_meta(verdict, action, confidence)
        except MetaGateReject as exc:
            self._record("meta_gate_reject", reason=str(exc))
            return None
        self._record("meta_verdict", verdict=verdict, action=action,
                     confidence=confidence, session=target)
        return verdict, action, confidence

    def _meta_review_fires(self) -> None:
        """drive-mode meta channel: independent second opinion on in-process
        watchdog fires recorded in the shared journal.

        In drive mode session supervision is the in-process watchdog's job, so
        the process-external loop cannot run its own T2 here. But `--meta`
        (intelligent review) must not become dead config: when enabled, this
        reviews each `watchdog_fire` the in-process watchdog journaled, with an
        independent model. The deterministic action was already taken by the
        watchdog; the model's verdict is RECORDED as audit/self-improvement data
        and never overrides the executed deterministic decision (intelligence
        advises, it does not overrule the deterministic gate).
        """
        if not self.meta_enabled or self.reporter is None:
            return
        if not getattr(self.reporter, "journal_path", None):
            return
        try:
            recs = self.reporter.journal_slice(since=self._last_meta_fire_ts)
        except Exception as exc:
            self._record("meta_error", err=f"journal read: {exc}")
            return
        for r in recs:
            if r.get("kind") != "watchdog_fire":
                continue
            ts = r.get("ts") or 0.0
            if ts > self._last_meta_fire_ts:
                self._last_meta_fire_ts = ts
            self.meta_analyze(session_id=r.get("session_id"))

    # -- run loop (fully wired: ingest + T1 + T2 + deadline + ladder) --------

    def run(self, *, once: bool = False,
            stop_when: "Callable[[], bool] | None" = None,
            supervise_sessions: bool = True) -> str:
        """Run the watchdog loop with its own clock.

        Each pass: ingest SSE events, check T1 health (restart if down), check T2
        session stall (escalate through the ladder with real actions), enforce the
        deadline. With `once=True` it does a single pass (for CLI `--once`/tests);
        otherwise it loops until the deadline, an L5 human escalation, or
        `stop_when()` (a caller-supplied completion check, e.g. the supervised
        workflow finished) returns True — in which case it returns `"workflow_done"`.

        `supervise_sessions=False` disables the T2 session-stall ladder: used in
        drive mode where the in-process watchdog (same SSE liveness fact source,
        same stall_sec) is the authoritative session supervisor with its richer
        recovery ladder (pause->resume->fallback->kill). The process-external
        loop then keeps only what it alone can do: T1 worker-health / docker
        restart and the global deadline. This is what structurally removes the
        dual-watchdog race (an external T2 firing at a different stall_sec than
        the in-process watchdog and hard-aborting the session before its recovery
        ladder can run).
        """
        while True:
            if stop_when is not None and stop_when():
                return "workflow_done"
            self.ingest_events()
            if supervise_sessions:
                if self.session_id is not None and self.client.health():
                    # T2: session stall — liveness is the SSE-activity timestamp
                    # (WORK_PLAN10). opencode's session_tokens are step-granular
                    # (persisted only at step-finish by an async projector) so they
                    # stay 0 during a long single-step generation; only the SSE
                    # /event stream is an immediate liveness signal. We deliberately
                    # do NOT read session_tokens here.
                    status = self.client.session_status(self.session_id)
                    busy = status == "busy"
                    stalled = self.watch.is_stalled(
                        time.time(), self.stall_sec, busy,
                        activity_ts=self._last_activity_ts)
                    if stalled:
                        if self.meta_enabled:
                            meta = self.meta_analyze()
                        else:
                            meta = None
                        if meta is not None:
                            verdict, action, confidence = meta
                        else:
                            # deterministic fallback (or no meta model available)
                            verdict, action, confidence = _verdict_for_stall(
                                self.watch.consecutive_stalls)
                        action = choose_action(verdict, action, confidence, self.ladder)
                        self._execute(action, verdict)
                        if action == L5_HUMAN:
                            return L5_HUMAN
                        # restart gives the worker a fresh start; abort/failed are retried
                        time.sleep(self.health_poll_sec * 2)
                        continue
            else:
                # drive mode: the in-process watchdog owns session recovery; the
                # external loop only offers the intelligent second-opinion on the
                # fires it journaled (never overruling the deterministic action).
                self._meta_review_fires()
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
