"""Statechart network primitives (pure domain, stage 1).

The long-term architecture (see ARCHITECTURE-statechart-network.md) replaces the
special-cased "constitution layer" with a set of *peer* state machines that
coordinate by exchanging signals. This module lays the foundation: a statechart
unit that can (a) receive signals and be woken into a callback/node, (b) send
signals to other units, and (c) emit audit events. Everything here is pure (no
I/O, no threads); the parallel runtime and bus wiring come in stage 2.

The signal protocol is application-level and orthogonal to whether units run on
threads or an event loop.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class SignalKind(str, Enum):
    """Semantic kinds of signals exchanged between statechart units.

    Control (constitution -> governed): STOP / RETRY / ESCALATE / NUDGE /
    PAUSE / RESUME. Probe (a unit asks another for a checkpoint): CHECKPOINT.
    Report (a unit replies with its state/timestamps): REPORT. Generic: NOTIFY.
    These are the *verbs*; the payload carries the details.
    """

    STOP = "stop"
    RETRY = "retry"
    ESCALATE = "escalate"
    NUDGE = "nudge"
    PAUSE = "pause"
    RESUME = "resume"
    CHECKPOINT = "checkpoint"
    REPORT = "report"
    NOTIFY = "notify"


@dataclass
class Signal:
    """A message exchanged between statechart units."""

    kind: SignalKind
    src: str          # source unit id
    dst: str          # target unit id ("*" = broadcast)
    payload: dict | None = None
    ts: str | None = None

    def has(self, key: str) -> bool:
        return bool(self.payload and key in self.payload)

    def get(self, key: str, default=None):
        return (self.payload or {}).get(key, default)


# Handlers are callables that react to a signal (may trigger a node/callback).
Handler = Callable[[Signal], None]


class StatechartUnit:
    """A unit of computation that can send/receive signals.

    A unit owns a dictionary of signal-handlers keyed by SignalKind. When it
    receives a signal it dispatches to the matching handler (the "wake into a
    callback" mechanism); unhandled signals return False so a caller can tell
    whether the message was consumed. `bus` is optional: when set, `send`/`emit`
    route through it; units may also be driven purely by direct `on_signal` calls.
    """

    def __init__(self, unit_id: str, bus: "Bus | None" = None, role: str = "governed") -> None:
        self.id = unit_id
        self.bus = bus
        self.role = role  # governed | watchdog | human (see runtime invariants)
        self._handlers: dict[SignalKind, Handler] = {}

    # -- signal registration -------------------------------------------------

    def register(self, kind: SignalKind, handler: Handler) -> "StatechartUnit":
        """Register a callback for a signal kind (one handler per kind)."""
        self._handlers[kind] = handler
        return self

    def handles(self, kind: SignalKind) -> bool:
        return kind in self._handlers

    # -- signal dispatch -----------------------------------------------------

    def on_signal(self, signal: Signal) -> bool:
        """Dispatch a signal to its handler. Returns False if unhandled."""
        handler = self._handlers.get(signal.kind)
        if handler is None:
            return False
        handler(signal)
        return True

    # -- outbound ------------------------------------------------------------

    def send(self, dst: str, kind: SignalKind, payload: dict | None = None) -> None:
        """Send a signal to another unit via the bus (requires a bus)."""
        if self.bus is None:
            return
        self.bus.dispatch(self.id, dst, kind, payload)

    def emit(self, event: str, **fields) -> None:
        """Emit an audit event onto the bus (if any)."""
        if self.bus is not None:
            self.bus.log(self.id, event, **fields)


class Bus:
    """Minimal message bus: routes signals to units and logs audit events.

    Point-to-point dispatch calls the target unit's `on_signal`; broadcast
    delivers to every unit. Logging is append-only (an in-memory list for now;
    stage 2 wires it to the JSONL ledger). Pure: no threads, no I/O.
    """

    def __init__(self) -> None:
        self._units: dict[str, StatechartUnit] = {}
        self._events: list[tuple[str, str, dict]] = []  # (src, event, fields)

    def register(self, unit: StatechartUnit) -> "Bus":
        self._units[unit.id] = unit
        return self

    def unit(self, unit_id: str) -> StatechartUnit | None:
        return self._units.get(unit_id)

    def ids(self) -> list[str]:
        return list(self._units)

    def dispatch(
        self,
        src: str,
        dst: str,
        kind: SignalKind,
        payload: dict | None = None,
    ) -> bool:
        """Deliver a point-to-point signal; returns True if the target handled it."""
        target = self._units.get(dst)
        if target is None:
            return False  # unknown target
        return target.on_signal(Signal(kind, src, dst, payload))

    def broadcast(self, src: str, kind: SignalKind, payload: dict | None = None) -> int:
        """Deliver a signal to every unit; returns how many handled it."""
        handled = 0
        for unit in self._units.values():
            if unit.on_signal(Signal(kind, src, "*", payload)):
                handled += 1
        return handled

    def log(self, src: str, event: str, **fields) -> None:
        self._events.append((src, event, fields))

    def events(self) -> list[tuple[str, str, dict]]:
        return list(self._events)