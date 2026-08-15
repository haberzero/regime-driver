"""Watchdog as a statechart unit (app layer).

The watchdog layer is a *peer* state machine that coordinates with working
state machines via signals, instead of a special-cased hardcoded guard. This
unit is a `StatechartUnit` (no intelligence) that receives REPORT signals from
working units and runs a **programmable policy** to decide the
response, then emits the corresponding control signal back over the bus.

It is deliberately I/O-free: probe data is fed *in* via signals, and the policy
rules are pure predicates. Acting (abort/pause/resume) is the *governed unit's*
job — the watchdog only decides and signals.

Policy model (see `watchdog_policy.py`):
  * REPORT -> SessionEvidence (SSE-activity, message timestamps, node, status,
    wall clock, ...),
  * `WatchdogPolicy.decide(evidence)` runs the operator-injectable rules and
    returns an action (nudge / interrupt / resume / fallback / kill),
  * the action maps to a control signal (NUDGE / PAUSE / RESUME / STOP).
  * a `meta=True` rule hit escalates to the intelligent reviewer (via the
    ESCALATE signal) before acting — the operator can gate soft triggers on an
    independent judgment.

Dead-loop detection (repetition) and the global guards (run timeout, node
budget, heartbeat loss) remain as deterministic, non-policy checks.
"""

from __future__ import annotations

import time

from ..core.repetition import RepetitionDetector
from ..core.statechart import Signal, SignalKind
from .blackboard import WORKFLOW_METRICS
from .statechart_runtime import ThreadedUnit
from .watchdog_policy import (
    L1_NUDGE,
    L2_INTERRUPT,
    L3_RESUME,
    L4_FALLBACK,
    L5_KILL,
    LADDER_ORDER,
    Rule,
    SessionEvidence,
    WatchdogPolicy,
)

# action -> control signal emitted to the governed workflow
_ACTION_SIGNAL = {
    L1_NUDGE: SignalKind.NUDGE,
    L2_INTERRUPT: SignalKind.PAUSE,
    L3_RESUME: SignalKind.RESUME,
    L4_FALLBACK: SignalKind.ESCALATE,   # handled by the supervisor ladder
    L5_KILL: SignalKind.STOP,
}

class WatchdogUnit(ThreadedUnit):
    """A peer, intelligence-free state machine that watches working units.

    It subscribes to REPORT signals (payload: session_id, node, activity_ts,
    status, latest_text, ...), builds a SessionEvidence, runs the configured
    `WatchdogPolicy`, and emits the chosen control signal. Global checks read
    the shared blackboard (total run time, node budget, stale heartbeat) and
    broadcast STOP when a whole-run condition is exceeded.

    The policy is injectable (`policy=...`); the default reproduces the
    classic behaviour (busy + no SSE activity -> kill after `stall_sec`),
    but now via a declared rule so operators can extend it.
    """

    def __init__(
        self,
        unit_id: str = "watchdog",
        stall_sec: float = 120.0,
        repetition: RepetitionDetector | None = None,
        control_dst: str = "*",
        bus=None,
        global_deadline_sec: float | None = None,
        max_global_nodes: int | None = None,
        heartbeat_stale_sec: float | None = None,
        policy: WatchdogPolicy | None = None,
        auto_resume_sec: float = 30.0,
        reporter: "Reporter | None" = None,
        run_id: str | None = None,
        hooks: "HookRegistry | None" = None,
    ) -> None:
        super().__init__(unit_id, bus, role="watchdog")
        self.stall_sec = stall_sec
        self.repetition = repetition or RepetitionDetector()
        self.control_dst = control_dst or "*"
        self.global_deadline_sec = global_deadline_sec
        self.max_global_nodes = max_global_nodes
        self.heartbeat_stale_sec = heartbeat_stale_sec
        self.policy = policy or default_policy(stall_sec)
        # unified extension registry: the `stall` hook fires on every
        # watchdog action (observe side-effect; never overrides the decision).
        self.hooks = hooks
        # A watchdog fire must land in the same report journal as the workflow
        # events, otherwise a stall verdict is invisible to report/forensics.
        # The reporter is the single event truth; `run_id` attributes the fire
        # to the workflow run.
        self.reporter = reporter
        self.run_id = run_id
        # Auto-recover: a paused session that stays silent for
        # `auto_resume_sec` is automatically resumed; if it still has no liveness
        # afterwards, the normal policy rules take over (eventual kill).
        self.auto_resume_sec = auto_resume_sec
        # per-session bookkeeping: last activity, first-busy time, pause-since,
        # fired guards
        self._last_activity: dict[str, float] = {}
        self._first_busy: dict[str, float] = {}
        self._pause_since: dict[str, float] = {}
        self._dead_loop_fired: set[str] = set()
        self._global_fired: set[str] = set()
        self.register(SignalKind.REPORT, self._on_report)
        self.register(SignalKind.STOP, lambda s: None)  # root invariant I2
        if self.bus is not None:
            self.on_event("blackboard.changed", self._on_blackboard_change)
            self.subscribe("blackboard.changed")

    # -- report intake ------------------------------------------------------

    def _on_report(self, signal: Signal) -> None:
        p = signal.payload or {}
        # dead-loop is a deterministic, non-policy check
        if p.get("latest_text"):
            res = self.repetition.check(p["latest_text"])
            if res.repeated and p.get("session_id") not in self._dead_loop_fired:
                self._dead_loop_fired.add(p.get("session_id", ""))
                self._emit_control(SignalKind.STOP, "dead_loop",
                                   f"repetition detected: {res.reason}", p,
                                   dst=signal.src or self.control_dst)
                self._scan_global()
                return
            if not res.repeated:
                self._dead_loop_fired.discard(p.get("session_id", ""))

        # policy decision over the evidence
        ev = self._evidence_from(p)
        sid = ev.session_id

        # A paused session must not hang forever. After
        # `auto_resume_sec` of silence we RESUME once (the governed unit injects
        # "continue"); if it STILL has no liveness afterwards, the normal policy
        # rules run and may eventually kill it.
        if ev.paused:
            self._pause_since.setdefault(sid, time.time())
            if time.time() - self._pause_since[sid] >= self.auto_resume_sec:
                self._pause_since.pop(sid, None)
                self._emit_control(SignalKind.RESUME, "auto_resume",
                                   f"paused {self.auto_resume_sec:.0f}s, auto-resuming",
                                   p, dst=signal.src or self.control_dst)
            self._scan_global()
            return
        self._pause_since.pop(sid, None)

        recovered = self._is_recovered(ev)
        action = self.policy.decide(ev, recovered=recovered)
        if action is not None:
            self._emit_action(action, ev, dst=signal.src or self.control_dst)
        self._scan_global()

    def _evidence_from(self, p: dict) -> SessionEvidence:
        sid = p.get("session_id", "")
        now = time.time()
        activity_ts = float(p.get("activity_ts") or 0.0)
        fresh = activity_ts > self._last_activity.get(sid, 0.0)
        if fresh:
            self._last_activity[sid] = activity_ts
            self._first_busy.pop(sid, None)
        if p.get("status") == "busy" and not fresh:
            # anchor the first-busy baseline only if we have no newer liveness
            self._first_busy.setdefault(sid, now)
        elif p.get("status") != "busy":
            self._first_busy.pop(sid, None)
        return SessionEvidence(
            session_id=sid,
            status=p.get("status"),
            activity_ts=self._last_activity.get(sid, 0.0),
            latest_message_ts=float(p.get("latest_message_ts") or 0.0),
            latest_message_age=float(p.get("latest_message_age") or 0.0),
            node=p.get("node"),
            phase=p.get("phase"),
            now=now,
            first_busy_ts=self._first_busy.get(sid, 0.0),
            paused=bool(p.get("paused")),
            meta={"fresh": fresh,
                  **({} if not isinstance(p.get("meta"), dict) else p["meta"])},
        )

    def _is_recovered(self, ev: SessionEvidence) -> bool:
        """A busy session with FRESH SSE activity (advanced since last report)
        is alive -> reset escalation. A PAUSED session (awaiting RESUME) is NOT
        a stall either — it was deliberately interrupted, so it must not be
        interrupted again while waiting; its escalation is held until resumed.
        """
        if ev.paused:
            return True  # held for recovery; do not re-interrupt
        if not ev.busy():
            self._last_activity.pop(ev.session_id, None)
            self._first_busy.pop(ev.session_id, None)
            return True
        # SSE progress advanced since our last report -> genuinely active
        if ev.meta.get("fresh"):
            return True
        return False

    def _emit_action(self, action: str, ev: SessionEvidence,
                     dst: str | None = None) -> None:
        # "meta:<action>" = the rule is meta-gated: emit ESCALATE so the
        # intelligent reviewer (supervisor meta_analyze) confirms before acting.
        meta_gated = action.startswith("meta:")
        real = action[len("meta:"):] if meta_gated else action
        kind = SignalKind.ESCALATE if meta_gated else _ACTION_SIGNAL.get(real, SignalKind.STOP)
        target = dst or self.control_dst
        detail = (f"watchdog policy '{self.policy.name}' -> {real}"
                  + (" (meta-confirm)" if meta_gated else ""))
        payload = {"reason": detail, "kind": real,
                   "watchdog": True, "session_id": ev.session_id,
                   "meta_gated": meta_gated}
        if target == "*":
            self.broadcast(kind, payload)
        else:
            self.send(target, kind, dict(payload))
        self.emit("watchdog_fire", kind=real, session=ev.session_id, detail=detail)
        self._record_fire(real, ev.session_id, detail)
        self._fire_stall_hook(real, ev.session_id, detail)

    def _emit_control(self, kind: SignalKind, event: str, detail: str,
                      payload: dict, dst: str | None = None) -> None:
        target = dst or self.control_dst
        if target == "*":
            self.broadcast(kind, {"reason": detail, "kind": event,
                                  "watchdog": True})
        else:
            self.send(target, kind, {"reason": detail, "kind": event,
                                     "watchdog": True})
        self.emit("watchdog_fire", kind=event,
                  session=payload.get("session_id"), detail=detail)
        self._record_fire(event, payload.get("session_id"), detail)
        self._fire_stall_hook(event, payload.get("session_id"), detail)

    def _fire_stall_hook(self, action: str, session: str | None,
                         detail: str) -> None:
        """Fire the `stall` lifecycle hook. Observer only: the
        deterministic watchdog action is already executed/journaled."""
        if self.hooks is None:
            return
        self.hooks.fire(
            "stall",
            on_error=lambda p, exc: logging.getLogger(__name__).warning(
                "hook %s error: %s", p, exc),
            **{"workflow": self.run_id, "session": session,
               "action": action, "reason": detail},
        )

    def _record_fire(self, kind: str, session: str | None, detail: str) -> None:
        """Persist a watchdog fire into the report journal (never raises)."""
        if self.reporter is not None:
            try:
                self.reporter.ingest(
                    kind="watchdog_fire", wf_id=self.run_id,
                    session_id=session,
                    event_type=kind,
                    detail={"reason": detail},
                )
            except Exception:
                # a journal failure must never kill the watchdog loop, but it must
                # be visible (a silently-dropped fire recreates the exact blind
                # spot this record exists to close)
                import logging
                logging.getLogger(__name__).warning(
                    "watchdog_fire journal record failed", exc_info=True)

    def _on_blackboard_change(self, payload: dict) -> None:
        """A blackboard metric changed -> re-run the global scan."""
        self._scan_global()

    # -- global scan (reads the shared blackboard) ---------------------------

    def _scan_global(self) -> None:
        """Check whole-run conditions across all workflows; stop the offender."""
        bb = self.bus.blackboard if self.bus is not None else None
        now = time.time()
        self._prune_stale(now)
        if bb is None:
            return
        workflows = self._workflow_ids(bb)
        for wid in workflows:
            p = f"{wid}."
            # 1. per-workflow run timeout
            if self.global_deadline_sec is not None:
                start = bb.get(f"{p}start_time")
                if start and now - float(start) > self.global_deadline_sec:
                    self._fire_once(f"global_timeout:{wid}", wid,
                                    ("global_timeout", f"{wid} exceeded {self.global_deadline_sec}s"))
            # 2. per-workflow node budget
            if self.max_global_nodes is not None:
                count = int(bb.get(f"{p}node_count") or 0)
                if count > self.max_global_nodes:
                    self._fire_once(f"global_budget:{wid}", wid,
                                    ("global_budget", f"{wid} node count {count} > {self.max_global_nodes}"))
            # 3. per-workflow heartbeat loss
            if self.heartbeat_stale_sec is not None:
                hb = bb.get(f"{p}heartbeat")
                if hb and now - float(hb) > self.heartbeat_stale_sec:
                    self._fire_once(f"heartbeat_loss:{wid}", wid,
                                    ("heartbeat_loss", f"{wid} heartbeat stale {self.heartbeat_stale_sec}s"))

    def _workflow_ids(self, bb) -> list[str]:
        """Derive workflow ids from blackboard keys (e.g. 'workflow-1.heartbeat')."""
        ids = set()
        for key in bb.keys():
            if "." in key:
                wid, _, metric = key.rpartition(".")
                if metric in WORKFLOW_METRICS:
                    ids.add(wid)
        return sorted(ids)

    def _fire_once(self, guard: str, wid: str, event: tuple[str, str]) -> None:
        if guard in self._global_fired:
            return
        self._global_fired.add(guard)
        self._emit_control(SignalKind.STOP, event[0], event[1], {}, dst=wid)

    def _prune_stale(self, now: float, max_age: float = 3600.0) -> None:
        """Drop per-session bookkeeping for sessions idle/absent for max_age."""
        if len(self._last_activity) < 64:
            return
        stale = [sid for sid, t in self._last_activity.items() if now - t > max_age]
        for sid in stale:
            self._last_activity.pop(sid, None)
            self._first_busy.pop(sid, None)
            self._pause_since.pop(sid, None)
            self.policy._ladders.pop(sid, None)  # bound per-session ladders


def default_policy(stall_sec: float) -> WatchdogPolicy:
    """The classic behaviour, expressed as a policy: busy without SSE activity
    for `stall_sec` escalates to a kill (the destructive backstop)."""
    from .watchdog_policy import no_activity_for

    return WatchdogPolicy(
        name="default",
        rules=[
            Rule(name="hard-stall",
                 predicate=no_activity_for(stall_sec),
                 action=L5_KILL,
                 reason="busy but no SSE activity beyond stall_sec"),
        ],
    )
