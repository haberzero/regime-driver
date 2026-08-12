"""Tests for stage-1 statechart primitives (signal protocol + message bus).

Validates the "peer state machines coordinate via signals" foundation: a unit
can register handlers, be woken into a callback by a signal, send signals to
another unit, and broadcast. Existing 125 tests must stay green (zero regression).
"""

import pytest

from regime_driver.core.statechart import Bus, Signal, SignalKind, StatechartUnit


def test_unit_dispatches_signal_to_handler():
    unit = StatechartUnit("work")
    seen = []
    unit.register(SignalKind.CHECKPOINT, lambda s: seen.append(s.get("node")))
    handled = unit.on_signal(Signal(SignalKind.CHECKPOINT, "watchdog", "work",
                                    {"node": "design"}))
    assert handled is True
    assert seen == ["design"]


def test_unhandled_signal_returns_false():
    unit = StatechartUnit("work")
    assert unit.on_signal(Signal(SignalKind.REPORT, "a", "work")) is False
    assert unit.handles(SignalKind.STOP) is False


def test_bus_routes_point_to_point():
    bus = Bus()
    called = []
    governor = StatechartUnit("watchdog")
    work = StatechartUnit("work")
    work.register(SignalKind.STOP, lambda s: called.append(("stop", s.src)))
    bus.register(governor).register(work)
    result = bus.dispatch("watchdog", "work", SignalKind.STOP)
    assert result is True
    assert called == [("stop", "watchdog")]


def test_bus_unknown_target_returns_false():
    bus = Bus()
    bus.register(StatechartUnit("a"))
    assert bus.dispatch("a", "nobody", SignalKind.NOTIFY) is False


def test_bus_broadcast_to_all_handlers():
    bus = Bus()
    got = []
    for name in ("w1", "w2", "w3"):
        u = StatechartUnit(name)
        u.register(SignalKind.NUDGE, lambda s, n=name: got.append(n))
        bus.register(u)
    handled = bus.broadcast("watchdog", SignalKind.NUDGE)
    assert handled == 3
    assert sorted(got) == ["w1", "w2", "w3"]


def test_unit_send_via_bus_and_emit():
    bus = Bus()
    got = []
    work = StatechartUnit("work")
    work.register(SignalKind.RETRY, lambda s: got.append(s.get("reason")))
    watchdog = StatechartUnit("watchdog", bus=bus)
    bus.register(watchdog).register(work)
    watchdog.send("work", SignalKind.RETRY, {"reason": "stall"})
    assert got == ["stall"]
    watchdog.emit("watchdog_ok")
    assert bus.events()[0][0:2] == ("watchdog", "watchdog_ok")


def test_signal_helpers():
    s = Signal(SignalKind.REPORT, "work", "watchdog", {"node": "implement"})
    assert s.has("node") is True
    assert s.has("missing") is False
    assert s.get("node") == "implement"
    assert s.get("missing", "?" ) == "?"


def test_unit_without_bus_send_is_noop():
    u = StatechartUnit("lonely")
    u.send("x", SignalKind.STOP)  # no bus -> no-op, no crash
    u.emit("evt")  # no bus -> no-op


def test_node_trigger_via_signal():
    """A unit can be 'woken into a node/callback' by a foreign signal."""
    bus = Bus()
    work = StatechartUnit("work")
    entered = []
    work.register(SignalKind.CHECKPOINT, lambda s: entered.append("self_assess"))
    work.register(SignalKind.STOP, lambda s: entered.append("aborted"))
    bus.register(work)
    watchdog = StatechartUnit("watchdog", bus=bus)
    bus.register(watchdog)
    watchdog.send("work", SignalKind.CHECKPOINT)
    watchdog.send("work", SignalKind.STOP)
    assert entered == ["self_assess", "aborted"]