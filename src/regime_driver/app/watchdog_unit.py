"""Watchdog as a statechart unit (app layer).

The watchdog layer is a *peer* state machine that coordinates with working
state machines via signals, instead of a special-cased hardcoded guard. This
unit is a `StatechartUnit` (no intelligence) that receives CHECKPOINT/REPORT
signals from working units (carrying node/timestamps/liveness/latest-text), runs
deterministic dead-loop + stall detection, and on a hit emits a control signal
(STOP) back over the bus.

It is deliberately I/O-free: probe data is fed *in* via signals, so the unit is
pure logic and fully testable in isolation.

Liveness signal (WORK_PLAN10): stall detection uses the SSE-activity timestamp
reported by the working unit (`payload["activity_ts"]`) — NOT token counts.
opencode's `session_tokens` are step-granular (persisted only at step-finish by
an async projector), so they stay 0 during a long single-step generation; the
SSE `/event` stream (`message.part.delta` ...) is the only immediate liveness
signal. A busy session is stalled only if it had no SSE progress for `stall_sec`.
"""

from __future__ import annotations

import time

from ..core.repetition import RepetitionDetector
from ..core.statechart import Signal, SignalKind
from .blackboard import WORKFLOW_METRICS
from .statechart_runtime import ThreadedUnit


class WatchdogUnit(ThreadedUnit):
    """A peer, intelligence-free state machine that watches working units.

    It subscribes to REPORT signals (payload: session_id, node, activity_ts,
    status, latest_text) and to blackboard changes, and broadcasts a STOP control
    signal when a dead loop, a stall, or a *global* condition (run timeout, node
    budget, cross-session heartbeat loss) is detected. It runs on the runtime as
    a watchdog unit (role="watchdog").

    Global checks read the shared blackboard (written by WorkflowUnit): total
    run time vs `global_deadline_sec`, total nodes vs `max_global_nodes`, and a
    stale-heartbeat cross-session stall. This gives the watchdog a
    multi-session / whole-run view, not just per-session.
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
    ) -> None:
        super().__init__(unit_id, bus, role="watchdog")
        self.stall_sec = stall_sec
        self.repetition = repetition or RepetitionDetector()
        self.control_dst = control_dst or "*"
        self.global_deadline_sec = global_deadline_sec
        self.max_global_nodes = max_global_nodes
        self.heartbeat_stale_sec = heartbeat_stale_sec
        # per-session stall bookkeeping: last SSE activity, first-busy time,
        # and the fired guard.
        self._last_activity: dict[str, float] = {}
        self._first_busy: dict[str, float] = {}
        self._stall_fired: set[str] = set()
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
        event = self._detect(
            session_id=p.get("session_id", ""),
            status=p.get("status"),
            activity_ts=float(p.get("activity_ts") or 0.0),
            latest_text=p.get("latest_text", ""),
        )
        if event is not None:
            # local detection -> STOP the reporting workflow (point-to-point)
            self._emit_control(event, p, dst=signal.src or self.control_dst)
        self._scan_global()

    def _on_blackboard_change(self, payload: dict) -> None:
        """A blackboard metric changed -> re-run the global scan."""
        self._scan_global()

    def _emit_control(self, event: tuple[str, str], payload: dict,
                      dst: str | None = None) -> None:
        kind, detail = event
        target = dst or self.control_dst
        if target == "*":
            self.broadcast(SignalKind.STOP, {"reason": detail, "kind": kind, "watchdog": True})
        else:
            self.send(target, SignalKind.STOP,
                      {"reason": detail, "kind": kind, "watchdog": True})
        self.emit("watchdog_fire", kind=kind, session=payload.get("session_id"), detail=detail)

    # -- global scan (reads the shared blackboard) ---------------------------

    def _scan_global(self) -> None:
        """Check whole-run conditions across all workflows; stop the offender."""
        bb = self.bus.blackboard if self.bus is not None else None
        now = time.time()
        # prune stale per-session bookkeeping for sessions with no reports for a
        # long time (they will be re-seeded fresh if they ever come back).
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
        self._emit_control(event, {}, dst=wid)

    def _prune_stale(self, now: float, max_age: float = 3600.0) -> None:
        """Drop per-session stall bookkeeping for sessions idle/absent for max_age.

        Bounds the dictionaries on long runs with many sessions (a session that
        stops reporting never comes back under a different id). Re-seeded fresh
        if the id ever returns.
        """
        if len(self._last_activity) < 64:
            return
        stale = [sid for sid, t in self._last_activity.items() if now - t > max_age]
        for sid in stale:
            self._last_activity.pop(sid, None)
            self._first_busy.pop(sid, None)
            self._stall_fired.discard(sid)

    def _detect(
        self,
        session_id: str,
        status: str | None,
        activity_ts: float = 0.0,
        latest_text: str = "",
    ) -> tuple[str, str] | None:
        """Return (kind, detail) if a dead loop or stall is detected, else None.

        Stall = a busy session with no SSE progress for `stall_sec`. The
        `activity_ts` (last SSE progress, from the working unit's REPORT) is the
        liveness clock; token counts are deliberately NOT used (step-granular,
        stale during long generations).
        """
        if not session_id:
            return None
        # 1. dead loop: latest text shows loop-style repetition (fire once)
        if latest_text:
            res = self.repetition.check(latest_text)
            if res.repeated:
                if session_id not in self._dead_loop_fired:
                    self._dead_loop_fired.add(session_id)
                    return ("dead_loop", f"repetition detected: {res.reason}")
            else:
                self._dead_loop_fired.discard(session_id)

        # 2. stall: busy but no SSE activity for stall_sec.
        prev = self._last_activity.get(session_id, 0.0)
        if status != "busy":
            # not busy (incl. a status-read error -> None) -> no stall possible;
            # reset all per-session bookkeeping so a later busy window starts
            # fresh. A genuinely stuck session whose status keeps erroring is
            # still bounded by the workflow's per-node timeout backstop.
            self._last_activity.pop(session_id, None)
            self._first_busy.pop(session_id, None)
            self._stall_fired.discard(session_id)
            return None
        if activity_ts > prev:
            self._last_activity[session_id] = activity_ts
            self._first_busy.pop(session_id, None)  # progress resets the clock
            self._stall_fired.discard(session_id)
            return None
        # busy and frozen. Anchor the silent window at the most recent known
        # progress; if we have NEVER seen progress (base 0), anchor at the first
        # busy observation so a busy-but-silent session still stalls.
        if prev > 0:
            base = max(activity_ts, prev)
        else:
            base = self._first_busy.setdefault(session_id, time.time())
        if (time.time() - base) >= self.stall_sec:
            if session_id not in self._stall_fired:
                self._stall_fired.add(session_id)
                return ("stall",
                        f"busy but no SSE activity for {self.stall_sec}s")
        return None
