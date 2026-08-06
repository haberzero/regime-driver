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


# --- global scan (blackboard) ----------------------------------------------

def _make_cons(bus, **kw):
    from regime_driver.app.blackboard import Blackboard
    cons = ConstitutionUnit(stall_sec=999, bus=bus, **kw)
    work = StatechartUnit("workflow")
    work.register(SignalKind.STOP, lambda s: None)
    bb = Blackboard(publisher=lambda ev, f: bus.publish("blackboard", ev, f))
    bus.blackboard = bb
    bus.register(cons).register(work)
    return cons, bb


def test_global_timeout_triggers_stop():
    bus = Bus()
    cons, bb = _make_cons(bus, global_deadline_sec=0.1)
    stopped = []
    work = StatechartUnit("workflow")
    work.register(SignalKind.STOP, lambda s: stopped.append(s.get("kind")))
    bus.register(work)
    bb.set("workflow.start_time", time.time() - 1.0)  # started long ago
    cons._scan_global()
    assert stopped == ["global_timeout"]


def test_global_node_budget_triggers_stop():
    bus = Bus()
    cons, bb = _make_cons(bus, max_global_nodes=3)
    stopped = []
    work = StatechartUnit("workflow")
    work.register(SignalKind.STOP, lambda s: stopped.append(s.get("kind")))
    bus.register(work)
    bb.set("workflow.node_count", 5)
    cons._scan_global()
    assert stopped == ["global_budget"]


def test_global_heartbeat_loss_triggers_stop():
    bus = Bus()
    cons, bb = _make_cons(bus, heartbeat_stale_sec=0.1)
    stopped = []
    work = StatechartUnit("workflow")
    work.register(SignalKind.STOP, lambda s: stopped.append(s.get("kind")))
    bus.register(work)
    bb.set("workflow.heartbeat", time.time() - 5.0)  # stale heartbeat
    cons._scan_global()
    assert stopped == ["heartbeat_loss"]


def test_global_scan_healthy_no_stop():
    bus = Bus()
    cons, bb = _make_cons(bus, global_deadline_sec=100, max_global_nodes=100,
                          heartbeat_stale_sec=100)
    stopped = []
    work = StatechartUnit("workflow")
    work.register(SignalKind.STOP, lambda s: stopped.append(1))
    bus.register(work)
    bb.set("workflow.start_time", time.time())
    bb.set("workflow.node_count", 2)
    bb.set("workflow.heartbeat", time.time())
    cons._scan_global()
    assert stopped == []


def test_global_fires_once():
    bus = Bus()
    cons, bb = _make_cons(bus, global_deadline_sec=0.1)
    stopped = []
    work = StatechartUnit("workflow")
    work.register(SignalKind.STOP, lambda s: stopped.append(1))
    bus.register(work)
    bb.set("workflow.start_time", time.time() - 2.0)
    cons._scan_global()
    cons._scan_global()  # already fired -> no second stop
    assert len(stopped) == 1