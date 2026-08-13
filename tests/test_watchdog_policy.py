"""Tests for the programmable watchdog policy (WORK_PLAN11).

The watchdog is now a small policy engine: evidence -> rules -> ladder. These
tests pin the injectable rule/ladder/probe mechanics and the interrupt-resume
recovery path (PAUSE/RESUME signals on the workflow).
"""

from __future__ import annotations

import time

import pytest

from regime_driver.app.watchdog_policy import (
    L1_NUDGE,
    L2_INTERRUPT,
    L3_RESUME,
    L4_FALLBACK,
    L5_KILL,
    LADDER_ORDER,
    Ladder,
    Rule,
    SessionEvidence,
    WatchdogPolicy,
    no_activity_for,
    no_message_for,
)
from regime_driver.core.statechart import Bus, Signal, SignalKind, StatechartUnit
from regime_driver.app.watchdog_unit import WatchdogUnit


def _ev(session="s1", *, status="busy", activity_ts=0.0, now=None, paused=False,
        latest_message_ts=0.0, first_busy_ts=0.0):
    return SessionEvidence(
        session_id=session, status=status, activity_ts=activity_ts,
        latest_message_ts=latest_message_ts, now=now or time.time(),
        first_busy_ts=first_busy_ts, paused=paused,
    )


# -- ladder -------------------------------------------------------------------

def test_ladder_escalates_forward():
    l = Ladder()
    assert l.current() == L1_NUDGE
    assert l.advance() == L2_INTERRUPT
    assert l.advance() == L3_RESUME
    assert l.advance() == L4_FALLBACK
    assert l.advance() == L5_KILL
    assert l.advance() == L5_KILL  # does not wrap


def test_ladder_reset():
    l = Ladder()
    l.advance(); l.advance()
    assert l.reset() == L1_NUDGE


def test_ladder_order_complete():
    assert list(LADDER_ORDER) == [L1_NUDGE, L2_INTERRUPT, L3_RESUME,
                                  L4_FALLBACK, L5_KILL]


# -- policy decide ------------------------------------------------------------

def test_policy_decide_no_hit_returns_none():
    p = WatchdogPolicy(rules=[Rule("never", lambda e: False, L1_NUDGE)])
    assert p.decide(_ev(activity_ts=time.time())) is None


def test_policy_decide_first_hit_wins():
    p = WatchdogPolicy(rules=[
        Rule("soft", no_activity_for(10), L2_INTERRUPT),
        Rule("hard", no_activity_for(60), L5_KILL),
    ])
    now = time.time()
    # 20s of silence -> soft rule hits -> interrupt
    assert p.decide(_ev(activity_ts=now - 20, now=now)) == L2_INTERRUPT


def test_policy_decide_escalates_to_hard():
    p = WatchdogPolicy(rules=[
        Rule("soft", no_activity_for(10), L2_INTERRUPT),
        Rule("hard", no_activity_for(60), L5_KILL),
    ])
    now = time.time()
    # 120s of silence -> both rules hit; first-hit wins would give interrupt,
    # but the ladder climbs to hard. Assert the CLIMBED action is kill.
    assert p.decide(_ev(activity_ts=now - 120, now=now)) == L5_KILL


def test_policy_fires_once_per_session_until_recovery():
    p = WatchdogPolicy(rules=[Rule("hard", no_activity_for(1), L5_KILL)])
    now = time.time()
    assert p.decide(_ev("s1", activity_ts=now - 5, now=now)) == L5_KILL
    # same session, still frozen, same rung -> fired guard, no repeat
    assert p.decide(_ev("s1", activity_ts=now - 5, now=now + 1)) is None
    # a DIFFERENT session escalates independently
    assert p.decide(_ev("s2", activity_ts=now - 5, now=now + 2)) == L5_KILL


def test_policy_recovery_resets_ladder():
    p = WatchdogPolicy(rules=[
        Rule("soft", no_activity_for(1), L2_INTERRUPT),
        Rule("hard", no_activity_for(5), L5_KILL),
    ])
    now = time.time()
    assert p.decide(_ev(activity_ts=now - 2, now=now)) == L2_INTERRUPT
    # session resumes (fresh activity) -> reset
    assert p.decide(_ev(activity_ts=time.time(), now=time.time()),
                    recovered=True) is None
    # a fresh short stall only re-climbs one rung (interrupt, not kill)
    assert p.decide(_ev(activity_ts=time.time() - 2, now=time.time())) == L2_INTERRUPT


def test_policy_ignores_broken_rule():
    def boom(e):
        raise RuntimeError("operator bug")
    p = WatchdogPolicy(rules=[Rule("broken", boom, L1_NUDGE),
                              Rule("hard", no_activity_for(1), L5_KILL)])
    now = time.time()
    assert p.decide(_ev(activity_ts=now - 5, now=now)) == L5_KILL


def test_probes_enrich_evidence():
    def probe(ev):
        ev.meta["probed"] = True
        return ev
    p = WatchdogPolicy(rules=[Rule("hard", lambda e: e.meta.get("probed"), L1_NUDGE)],
                       probes=[probe])
    assert p.decide(_ev()) == L1_NUDGE


def test_convenience_predicates():
    now = time.time()
    assert no_activity_for(5)(_ev(activity_ts=now - 6, now=now)) is True
    assert no_activity_for(5)(_ev(activity_ts=now - 3, now=now)) is False
    # idle session is never stalled by no_activity_for
    assert no_activity_for(5)(_ev(status="idle", activity_ts=now - 6, now=now)) is False
    assert no_message_for(5)(_ev(latest_message_ts=now - 6, now=now)) is True


def test_silent_for_falls_back_to_first_busy():
    now = time.time()
    # no activity, no message -> falls back to first_busy_ts
    ev = _ev(activity_ts=0, latest_message_ts=0, first_busy_ts=now - 10, now=now)
    assert ev.silent_for() >= 10


# -- watchdog integration: signal emission ------------------------------------

def _mk_watchdog(stall_sec=0.1):
    bus = Bus()
    wd = WatchdogUnit(stall_sec=stall_sec, bus=bus)
    work = StatechartUnit("work")
    got = []
    for k in (SignalKind.NUDGE, SignalKind.PAUSE, SignalKind.RESUME, SignalKind.STOP):
        work.register(k, lambda s, k=k: got.append((k.value, s.get("kind"))))
    bus.register(wd).register(work)
    return wd, got


def _feed(wd, payload):
    wd._on_report(Signal(SignalKind.REPORT, "work", wd.id, payload))


def test_watchdog_policy_action_maps_to_signal():
    wd, got = _mk_watchdog(stall_sec=0.1)
    t0 = time.time()
    _feed(wd, {"session_id": "s1", "status": "busy", "activity_ts": t0,
               "latest_text": ""})
    _feed(wd, {"session_id": "s1", "status": "busy", "activity_ts": t0,
               "latest_text": ""})
    time.sleep(0.15)
    _feed(wd, {"session_id": "s1", "status": "busy", "activity_ts": t0,
               "latest_text": ""})
    # default policy -> kill -> STOP
    assert ("stop", "kill") in got


def test_watchdog_custom_policy_emits_pause():
    """An operator policy that prefers interrupt-resume over kill emits PAUSE."""
    p = WatchdogPolicy(name="interrupt-first", rules=[
        Rule("soft", no_activity_for(0.1), L2_INTERRUPT),
        Rule("hard", no_activity_for(60), L5_KILL),
    ])
    bus = Bus()
    wd = WatchdogUnit(policy=p, stall_sec=60, bus=bus)
    work = StatechartUnit("work")
    got = []
    for k in (SignalKind.PAUSE, SignalKind.STOP):
        work.register(k, lambda s, k=k: got.append((k.value, s.get("kind"))))
    bus.register(wd).register(work)
    t0 = time.time()
    _feed(wd, {"session_id": "s1", "status": "busy", "activity_ts": t0,
               "latest_text": ""})
    _feed(wd, {"session_id": "s1", "status": "busy", "activity_ts": t0,
               "latest_text": ""})
    time.sleep(0.15)
    _feed(wd, {"session_id": "s1", "status": "busy", "activity_ts": t0,
               "latest_text": ""})
    assert ("pause", "interrupt") in got
    assert ("stop", "kill") not in got


def test_watchdog_paused_session_not_reinterrupted():
    """A paused session (awaiting RESUME) must NOT be interrupted again."""
    p = WatchdogPolicy(name="interrupt-first", rules=[
        Rule("soft", no_activity_for(0.1), L2_INTERRUPT),
    ])
    bus = Bus()
    wd = WatchdogUnit(policy=p, stall_sec=60, bus=bus)
    work = StatechartUnit("work")
    got = []
    work.register(SignalKind.PAUSE, lambda s: got.append(s.get("kind")))
    bus.register(wd).register(work)
    t0 = time.time()
    _feed(wd, {"session_id": "s1", "status": "busy", "activity_ts": t0,
               "latest_text": "", "paused": False})
    _feed(wd, {"session_id": "s1", "status": "busy", "activity_ts": t0,
               "latest_text": "", "paused": False})
    time.sleep(0.15)
    _feed(wd, {"session_id": "s1", "status": "busy", "activity_ts": t0,
               "latest_text": "", "paused": False})
    assert got == ["interrupt"]  # first pause
    # now paused=True: further reports must NOT re-interrupt
    _feed(wd, {"session_id": "s1", "status": "busy", "activity_ts": t0,
               "latest_text": "", "paused": True})
    _feed(wd, {"session_id": "s1", "status": "busy", "activity_ts": t0,
               "latest_text": "", "paused": True})
    assert got == ["interrupt"]  # unchanged


def test_workflow_pause_resume_signals_roundtrip():
    """PAUSE freezes the workflow, RESUME unfreezes and re-dispatches."""
    from regime_driver.app.workflow_unit import WorkflowUnit
    from regime_driver.infra.settings import Settings
    from regime_driver.infra.regime_loader import load_regime
    from regime_driver.core.statechart import Bus
    from regime_driver.core.state_machine import StateMachine

    class FakeClient:
        def __init__(self):
            self.msgs = {}
            self.sent = []
            self.aborted = []

        def create_session(self, title):
            return "mock-ses"

        def session_status(self, sid):
            return "idle"

        def session_tokens(self, sid):
            return 0, 0

        def abort_session(self, sid):
            self.aborted.append(sid)

        def send_message(self, sid, text, agent):
            self.sent.append((sid, text, agent))
            if "监督恢复" in text or "监督提示" in text:
                # resume/nudge prompt -> the developer produces a fresh report
                body = "done\n[WORK_DONE]"
                self.msgs[sid] = [type("M", (), {
                    "role": "assistant", "text": body, "reply": body,
                    "error": None, "completed": str(time.time()), "finish": "stop",
                    "ts": str(time.time()),
                })()]
            elif agent == "reviewer":
                import re as _re
                m = _re.search(r"当前节点[:：]\s*(\w+)", text)
                node = m.group(1) if m else "design"
                v = {"node": node, "verdict": "advance", "action": "advance",
                     "next_state": {"design": "implement", "test": "wrap"}.get(node, "wrap"),
                     "confidence": 0.9, "reason": "ok"}
                self.msgs[sid] = [type("M", (), {
                    "role": "assistant", "text": __import__("json").dumps(v),
                    "reply": __import__("json").dumps(v), "error": None,
                    "completed": str(time.time()), "finish": "stop",
                    "ts": str(time.time()),
                })()]
            else:
                # FIRST developer dispatch never completes (stays busy so the
                # workflow can be PAUSED deterministically); later dispatches
                # complete normally.
                if not getattr(self, "_first_dev_done", False):
                    self._first_dev_done = True
                    self.msgs[sid] = [type("M", (), {
                        "role": "assistant", "text": "thinking...", "reply": "",
                        "error": None, "completed": None, "finish": None, "ts": None,
                    })()]
                else:
                    body = "done\n[WORK_DONE]"
                    self.msgs[sid] = [type("M", (), {
                        "role": "assistant", "text": body, "reply": body,
                        "error": None, "completed": str(time.time()), "finish": "stop",
                        "ts": str(time.time()),
                    })()]

        def read_messages(self, sid):
            return self.msgs.get(sid, [])

        def event_stream(self, reconnect=False, max_retries=1):
            yield {"event": "server.connected", "data": {}}

    sm = load_regime()
    client = FakeClient()
    unit = WorkflowUnit(Settings(monitor_enabled=False, poll_sec=0.1),
                        sm, client, poll_sec=0.1)
    unit.start()
    unit.submit("任务")
    time.sleep(0.2)
    # pause mid-run
    unit.deliver(Signal(SignalKind.PAUSE, "watchdog", unit.id,
                        {"reason": "test pause"}))
    deadline = time.time() + 2.0
    while not unit._paused and time.time() < deadline:
        time.sleep(0.02)
    assert unit._paused is True
    assert client.aborted  # current generation was aborted, session kept
    # resume
    unit.deliver(Signal(SignalKind.RESUME, "watchdog", unit.id,
                        {"reason": "test resume"}))
    deadline = time.time() + 3.0
    while unit.result() is None and time.time() < deadline:
        time.sleep(0.05)
    unit.stop()
    assert unit.result() is not None
    # a resume prompt was dispatched to the session
    assert any("监督恢复" in t for _, t, _ in client.sent)


def test_workflow_nudge_sends_light_prompt():
    from regime_driver.app.workflow_unit import WorkflowUnit
    from regime_driver.infra.settings import Settings
    from regime_driver.infra.regime_loader import load_regime

    class FakeClient:
        def __init__(self):
            self.msgs = {}
            self.sent = []
            self.aborted = []

        def create_session(self, title):
            return "mock-ses"

        def session_status(self, sid):
            return "busy"

        def session_tokens(self, sid):
            return 0, 0

        def abort_session(self, sid):
            self.aborted.append(sid)

        def send_message(self, sid, text, agent):
            self.sent.append((sid, text, agent))
            self.msgs[sid] = [type("M", (), {
                "role": "assistant", "text": "", "reply": "", "error": None,
                "completed": None, "finish": None, "ts": None,
            })()]

        def read_messages(self, sid):
            return self.msgs.get(sid, [])

        def event_stream(self, reconnect=False, max_retries=1):
            yield {"event": "server.connected", "data": {}}

    sm = load_regime()
    client = FakeClient()
    unit = WorkflowUnit(Settings(monitor_enabled=False, poll_sec=0.1),
                        sm, client, poll_sec=0.1)
    unit.start()
    unit.submit("任务")
    time.sleep(0.2)
    unit.deliver(Signal(SignalKind.NUDGE, "watchdog", unit.id,
                        {"reason": "test nudge"}))
    time.sleep(0.2)
    unit.stop()
    assert any("监督提示" in t for _, t, _ in client.sent)


# -- WORK_PLAN11 review fixes ------------------------------------------------

def test_auto_resume_after_pause_timeout():
    """A paused session that stays silent is auto-RESUMEd after auto_resume_sec
    (it must not hang forever), and is NOT killed while paused."""
    p = WatchdogPolicy(rules=[
        Rule("hard", no_activity_for(60), L5_KILL),
    ])
    bus = Bus()
    wd = WatchdogUnit(policy=p, stall_sec=60, bus=bus, auto_resume_sec=0.1)
    work = StatechartUnit("work")
    got = []
    for k in (SignalKind.RESUME, SignalKind.STOP):
        work.register(k, lambda s, k=k: got.append((k.value, s.get("kind"))))
    bus.register(wd).register(work)
    t0 = time.time()
    # paused report
    _feed(wd, {"session_id": "s1", "status": "busy", "activity_ts": t0,
               "latest_text": "", "paused": True})
    time.sleep(0.2)  # exceed auto_resume_sec
    _feed(wd, {"session_id": "s1", "status": "busy", "activity_ts": t0,
               "latest_text": "", "paused": True})
    assert ("resume", "auto_resume") in got, "paused session must auto-resume"
    assert ("stop", "kill") not in got, "paused session must NOT be killed"


def test_meta_gated_rule_emits_escalate_not_direct_action():
    """A meta=True rule returns meta:<action> and the watchdog emits ESCALATE
    (so an independent reviewer confirms before acting), never the raw kill."""
    p = WatchdogPolicy(rules=[
        Rule("soft-meta", no_activity_for(0.1), L2_INTERRUPT, meta=True),
    ])
    bus = Bus()
    wd = WatchdogUnit(policy=p, stall_sec=60, bus=bus)
    work = StatechartUnit("work")
    got = []
    for k in (SignalKind.ESCALATE, SignalKind.PAUSE):
        work.register(k, lambda s, k=k: got.append((k.value, s.get("kind"))))
    bus.register(wd).register(work)
    t0 = time.time()
    _feed(wd, {"session_id": "s1", "status": "busy", "activity_ts": t0,
               "latest_text": ""})
    _feed(wd, {"session_id": "s1", "status": "busy", "activity_ts": t0,
               "latest_text": ""})
    time.sleep(0.15)
    _feed(wd, {"session_id": "s1", "status": "busy", "activity_ts": t0,
               "latest_text": ""})
    assert ("escalate", "interrupt") in got
    assert ("pause", "interrupt") not in got, "meta-gated must not act directly"


def test_nudge_fires_once_per_episode():
    """A nudge (rung 0) fires once per episode, not on every report."""
    p = WatchdogPolicy(rules=[Rule("poke", no_activity_for(0.1), L1_NUDGE)])
    now = time.time()
    assert p.decide(_ev(activity_ts=now - 5, now=now)) == L1_NUDGE
    assert p.decide(_ev(activity_ts=now - 6, now=now + 0.2)) is None  # fired once
    # recovery resets and it can nudge again
    assert p.decide(_ev(activity_ts=time.time(), now=time.time()),
                    recovered=True) is None
    assert p.decide(_ev(activity_ts=time.time() - 5, now=time.time())) == L1_NUDGE


def test_silent_for_uses_most_recent_liveness():
    """silent_for must use the MAX of activity and message timestamps, so a
    fresh message is never masked by stale SSE activity."""
    now = time.time()
    ev = _ev(activity_ts=now - 100, latest_message_ts=now - 2, now=now)
    assert ev.silent_for() <= 2, "must use the newest liveness, not old activity"


def test_unknown_action_raises_at_construction():
    from regime_driver.app.watchdog_policy import WatchdogPolicy, Rule
    import pytest as _pytest
    with _pytest.raises(ValueError):
        WatchdogPolicy(rules=[Rule("bad", lambda e: True, "not_a_ladder_action")])


def test_policy_from_json_empty_returns_none():
    from regime_driver.app.watchdog_policy import policy_from_json
    assert policy_from_json(None) is None
    assert policy_from_json("") is None


def test_policy_from_json_builds_rules():
    from regime_driver.app.watchdog_policy import policy_from_json
    p = policy_from_json('{"soft_sec": 30, "hard_sec": 600, "name": "op"}')
    assert p is not None
    assert p.name == "op"
    names = {r.name for r in p.rules}
    assert "op-soft" in names and "op-hard" in names
    now = time.time()
    # 100s of silence -> soft (interrupt) fired
    assert p.decide(_ev(activity_ts=now - 100, now=now)) == L2_INTERRUPT


def test_policy_from_json_meta_gate():
    from regime_driver.app.watchdog_policy import policy_from_json
    p = policy_from_json('{"soft_sec": 10, "meta_gate_soft": true}')
    now = time.time()
    act = p.decide(_ev(activity_ts=now - 20, now=now))
    assert act is not None and act.startswith("meta:")
