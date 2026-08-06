"""Parallel statechart runtime (app layer, stage 2).

Stage 1 established the pure signal protocol (core/statechart.py). Stage 2 makes
the state charts actually *run in parallel*: each unit gets its own thread and a
message queue, and a Runtime delivers signals asynchronously to the target
unit's queue. This is the "peer state machines, no hierarchy" model — units
drive each other by posting signals, and point-to-point delivery is thread-safe
(queue.Queue).

The Runtime is deliberately independent of the existing RegimeDriver main flow
(at this stage). It is pure concurrency plumbing; wiring the constitution unit
into the real run is stage 3.
"""

from __future__ import annotations

import queue
import threading

from ..core.statechart import Bus, Signal, SignalKind, StatechartUnit


class ThreadedUnit(StatechartUnit):
    """A StatechartUnit that runs on its own thread, consuming posted signals.

    Signals are delivered to its queue (thread-safe); its run loop calls
    `on_signal` serially on its own thread. Handler exceptions are swallowed so
    one misbehaving unit cannot kill the others or the runtime.
    """

    def __init__(self, unit_id: str, bus: Bus | None = None, role: str = "governed") -> None:
        super().__init__(unit_id, bus, role=role)
        self._q: queue.Queue[Signal] = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> "ThreadedUnit":
        if self._thread is not None and self._thread.is_alive():
            return self
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, daemon=True, name=f"statechart-{self.id}"
        )
        self._thread.start()
        return self

    def stop(self, timeout: float = 2.0) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None

    def deliver(self, signal: Signal) -> None:
        """Post a signal onto this unit's queue (thread-safe, non-blocking)."""
        self._q.put(signal)

    # -- run loop -----------------------------------------------------------

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                signal = self._q.get(timeout=0.2)
            except queue.Empty:
                continue
            try:
                self.on_signal(signal)
            except Exception:
                # a unit-level handler error must not kill the runtime
                pass


class Runtime:
    """Owns a set of ThreadedUnits and routes signals between them.

    `post` delivers a signal to the target unit's queue (asynchronous, safe to
    call from any thread), so a unit can drive another unit while both run on
    their own threads. `broadcast` delivers to every unit.
    """

    def __init__(
        self,
        bus: Bus | None = None,
        max_meta_depth: int = 8,
        enforce_invariants: bool = True,
    ) -> None:
        self.bus = bus or Bus()
        self.units: dict[str, ThreadedUnit] = {}
        self.meta_depth = 0
        self.max_meta_depth = max_meta_depth
        self.enforce_invariants = enforce_invariants

    def register(self, unit: ThreadedUnit) -> "Runtime":
        self.bus.register(unit)
        self.units[unit.id] = unit
        return self

    def start(self) -> "Runtime":
        if self.enforce_invariants:
            from .runtime_invariants import enforce

            result = enforce(list(self.units.values()),
                             meta_depth=self.meta_depth,
                             max_meta_depth=self.max_meta_depth)
            if not result.ok:
                raise RuntimeError(
                    "root invariant violation; refusing to start: "
                    + "; ".join(result.violations)
                )
        for unit in self.units.values():
            unit.start()
        return self

    def stop(self, timeout: float = 2.0) -> None:
        for unit in self.units.values():
            unit.stop(timeout)

    def post(self, src: str, dst: str, kind: SignalKind, payload: dict | None = None) -> bool:
        """Asynchronously deliver a signal to a unit's queue. Returns False if
        the target is unknown."""
        target = self.units.get(dst)
        if target is None:
            return False
        target.deliver(Signal(kind, src, dst, payload))
        return True

    def broadcast(self, src: str, kind: SignalKind, payload: dict | None = None) -> int:
        for unit in self.units.values():
            unit.deliver(Signal(kind, src, "*", payload))
        return len(self.units)

    def log(self, src: str, event: str, **fields) -> None:
        self.bus.log(src, event, **fields)