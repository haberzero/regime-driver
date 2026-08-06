"""Tests for stage-3 constitution-as-statechart-unit (signal-protocol watchdog).

Proves the "constitution = intelligence-free peer state machine" thesis: a
ConstitutionUnit fed REPORT signals reproduces the current Monitor's dead-loop
and stall detection, and emits a STOP control signal over the bus. The existing
Monitor is untouched (zero regression); this establishes capability equivalence
on the signal protocol.
"""

import time

from regime_driver.app.constitution_unit import ConstitutionUnit
from regime_driver.core.statechart import Bus, Signal, SignalKind, StatechartUnit


def _report(session, status="busy", output=100, latest=""):
    return {"session_id": session, "status": status, "output": output, "latest_text": latest}


def _feed(unit, payload):
    unit._on_report(Signal(SignalKind.REPORT, "work", unit.id, payload))


def _deadline(sec=3.0):
    return time.time() + sec


def test_healthy_report_no_control_signal():
    bus = Bus()
    cons = ConstitutionUnit(stall_sec=120, bus=bus)
    work = StatechartUnit("work")
    stopped = []
    work.register(SignalKind.STOP, lambda s: stopped.append(s))
    bus.register(cons).register(work)
    _feed(cons, _report("s1", output=100))
    _feed(cons, _report("s1", output=200))  # output growing -> healthy
    assert stopped == []


def test_stall_detected_emits_stop():
    bus = Bus()
    cons = ConstitutionUnit(stall_sec=0.1, bus=bus)  # tiny threshold
    work = StatechartUnit("work")
    stopped = []
    work.register(SignalKind.STOP, lambda s: stopped.append(s.get("watchdog")))
    bus.register(cons).register(work)
    _feed(cons, _report("s1", output=100))  # baseline
    _feed(cons, _report("s1", output=100))  # output stops growing -> clock starts
    time.sleep(0.15)
    _feed(cons, _report("s1", output=100))  # past stall_sec, still busy -> fire
    assert stopped == [True]


def test_dead_loop_detected_emits_stop():
    bus = Bus()
    cons = ConstitutionUnit(stall_sec=120, bus=bus)
    work = StatechartUnit("work")
    stopped = []
    work.register(SignalKind.STOP, lambda s: stopped.append(s.get("kind")))
    bus.register(cons).register(work)
    # highly repetitive text triggers the repetition detector
    _feed(cons, _report("s1", latest="fix fix fix fix fix fix fix fix fix fix fix fix fix"))
    assert stopped == ["dead_loop"]


def test_stall_fires_once_per_session():
    bus = Bus()
    cons = ConstitutionUnit(stall_sec=0.1, bus=bus,
                            control_dst="work")
    work = StatechartUnit("work")
    stopped = []
    work.register(SignalKind.STOP, lambda s: stopped.append(1))
    bus.register(cons).register(work)
    _feed(cons, _report("s1", output=100))  # baseline
    _feed(cons, _report("s1", output=100))  # clock starts
    time.sleep(0.15)
    _feed(cons, _report("s1", output=100))  # fires once
    _feed(cons, _report("s1", output=100))  # same output, already fired
    assert len(stopped) == 1


def test_idle_report_resets_stall():
    bus = Bus()
    cons = ConstitutionUnit(stall_sec=0.1, bus=bus)
    work = StatechartUnit("work")
    stopped = []
    work.register(SignalKind.STOP, lambda s: stopped.append(1))
    bus.register(cons).register(work)
    _feed(cons, _report("s1", output=100))  # baseline
    _feed(cons, _report("s1", output=100))  # clock starts
    time.sleep(0.15)
    _feed(cons, _report("s1", status="idle", output=100))  # not busy -> reset
    _feed(cons, _report("s1", status="busy", output=100))  # fresh stall window
    assert stopped == []


def test_audit_event_logged_on_fire():
    bus = Bus()
    cons = ConstitutionUnit(stall_sec=0.1, bus=bus)
    work = StatechartUnit("work")
    work.register(SignalKind.STOP, lambda s: None)
    bus.register(cons).register(work)
    _feed(cons, _report("s1", output=100))  # baseline
    _feed(cons, _report("s1", output=100))  # clock starts
    time.sleep(0.15)
    _feed(cons, _report("s1", output=100))  # fires
    fired = [e for e in bus.events() if e[1] == "watchdog_fire"]
    assert fired and fired[0][2]["kind"] == "stall"