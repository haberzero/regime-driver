"""Constitution as a statechart unit (app layer, stage 3).

The constitution layer is a *peer* state machine that coordinates with working
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
from .statechart_runtime import ThreadedUnit


class ConstitutionUnit(ThreadedUnit):
    """A peer, intelligence-free state machine that watches working units.

    It subscribes to REPORT signals (payload: session_id, node, output, status,
    latest_text) and broadcasts a STOP/ESCALATE control signal when a dead loop
    or stall is detected. It holds the detection state (stall_since, fired sets)
    just like the current Monitor, so behaviour is equivalent. It runs on the
    runtime as a watchdog unit (role="watchdog").
    """

    def __init__(
        self,
        unit_id: str = "constitution",
        stall_sec: float = 120.0,
        repetition: RepetitionDetector | None = None,
        control_dst: str = "*",
        bus=None,
    ) -> None:
        super().__init__(unit_id, bus, role="watchdog")
        self.stall_sec = stall_sec
        self.repetition = repetition or RepetitionDetector()
        self.control_dst = control_dst or "*"
        self._last_output: dict[str, int] = {}
        self._stall_since: dict[str, float] = {}
        self._stall_fired: set[str] = set()
        self._dead_loop_fired: set[str] = set()
        self.register(SignalKind.REPORT, self._on_report)
        self.register(SignalKind.STOP, lambda s: None)  # root invariant I2

    # -- report intake ------------------------------------------------------

    def _on_report(self, signal: Signal) -> None:
        p = signal.payload or {}
        event = self._detect(
            session_id=p.get("session_id", ""),
            status=p.get("status"),
            output=int(p.get("output") or 0),
            latest_text=p.get("latest_text", ""),
        )
        if event is not None:
            self._emit_control(event, p)

    def _emit_control(self, event: tuple[str, str], payload: dict) -> None:
        kind, detail = event
        # both a dead loop and a stall warrant a stop; the `kind` is preserved in
        # the audit event so a user can distinguish (and later map to NUDGE etc.)
        if self.control_dst == "*":
            self.broadcast(SignalKind.STOP, {"reason": detail, "kind": kind, "watchdog": True})
        else:
            self.send(self.control_dst, SignalKind.STOP,
                      {"reason": detail, "kind": kind, "watchdog": True})
        self.emit("watchdog_fire", kind=kind, session=payload.get("session_id"), detail=detail)

    def _detect(
        self,
        session_id: str,
        status: str | None,
        output: int,
        latest_text: str,
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

        # 2. stall: busy but no output growth for stall_sec
        prev = self._last_output.get(session_id)
        if prev is not None and output == prev:
            if status == "busy":
                since = self._stall_since.setdefault(session_id, time.time())
                if time.time() - since >= self.stall_sec:
                    if session_id not in self._stall_fired:
                        self._stall_fired.add(session_id)
                        return ("stall", f"busy but no output growth for {self.stall_sec}s")
            else:
                self._stall_since.pop(session_id, None)
                self._stall_fired.discard(session_id)
        else:
            self._last_output[session_id] = output
            self._stall_since.pop(session_id, None)
            self._stall_fired.discard(session_id)
        return None