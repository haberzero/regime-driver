"""Watchdog as a statechart unit (app layer).

The watchdog layer is a *peer* state machine that coordinates with working
state machines via signals, instead of a special-cased hardcoded guard. This
unit is a `StatechartUnit` (no intelligence) that receives CHECKPOINT/REPORT
signals from working units (carrying node/timestamps/output/latest-text), runs
deterministic dead-loop + stall detection, and on a hit emits a control signal
(STOP) back over the bus.

It is deliberately I/O-free: probe data is fed *in* via signals, so the unit is
pure logic and fully testable in isolation.
"""

from __future__ import annotations

import time

from ..core.repetition import RepetitionDetector
from ..core.statechart import Signal, SignalKind
from .blackboard import WORKFLOW_METRICS
from .statechart_runtime import ThreadedUnit


class WatchdogUnit(ThreadedUnit):
    """A peer, intelligence-free state machine that watches working units.

    It subscribes to REPORT signals (payload: session_id, node, output, status,
    latest_text) and to blackboard changes, and broadcasts a STOP control signal
    when a dead loop, stall, or a *global* condition (run timeout, node budget,
    cross-session heartbeat loss) is detected. It runs on the runtime as a
    watchdog unit (role="watchdog").

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
        self._last_output: dict[tuple[str, str], int] = {}
        self._last_reasoning: dict[tuple[str, str], int] = {}
        self._stall_since: dict[str, float] = {}
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
            output=int(p.get("output") or 0),
            reasoning=int(p.get("reasoning") or 0),
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
        if bb is None:
            return
        now = time.time()
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

    def _detect(
        self,
        session_id: str,
        status: str | None,
        output: int,
        reasoning: int = 0,
        latest_text: str = "",
    ) -> tuple[str, str] | None:
        """Return (kind, detail) if a dead loop or stall is detected, else None."""
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

        # 2. stall: busy but no growth (output NOR reasoning) for stall_sec.
        #    Reasoning token growth is liveness too: long "thinking" phases of
        #    hard tasks stream reasoning before any text lands, and counting
        #    only output would false-kill a healthy deep-reasoning session.
        key = (session_id, "out")
        prev_out = self._last_output.get(key)
        if prev_out is not None and output == prev_out:
            key_r = (session_id, "rsn")
            prev_rsn = self._last_reasoning.get(key_r)
            if prev_rsn is not None and reasoning == prev_rsn:
                if status == "busy":
                    since = self._stall_since.setdefault(session_id, time.time())
                    if time.time() - since >= self.stall_sec:
                        if session_id not in self._stall_fired:
                            self._stall_fired.add(session_id)
                            return ("stall",
                                    f"busy but no growth (output nor reasoning) "
                                    f"for {self.stall_sec}s")
                else:
                    self._stall_since.pop(session_id, None)
                    self._stall_fired.discard(session_id)
            else:
                self._last_reasoning[key_r] = reasoning
                self._stall_since.pop(session_id, None)
                self._stall_fired.discard(session_id)
        else:
            self._last_output[key] = output
            if self._last_reasoning.get((session_id, "rsn")) is None:
                self._last_reasoning[(session_id, "rsn")] = reasoning
            self._stall_since.pop(session_id, None)
            self._stall_fired.discard(session_id)
        return None