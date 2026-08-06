"""Tests for the WorkflowUnit (governed state machine driving a flow)."""

import json
import re
import time

from regime_driver.app.workflow_unit import WorkflowUnit
from regime_driver.core.models import Outcome
from regime_driver.core.statechart import SignalKind
from regime_driver.infra.ledger import Ledger
from regime_driver.infra.regime_loader import load_regime
from regime_driver.infra.settings import Settings

# successor map for the real code_workflow: judge node -> valid advance target
SUCC = {"design": "implement", "test": "wrap"}


class Message:
    def __init__(self, role, text="", error=None):
        self.role = role
        self.text = text
        self.error = error


class FakeClient:
    def __init__(self):
        self.created = 0
        self.msgs = {}
        self.status = {}
        self.tokens = {}

    def create_session(self, title):
        self.created += 1
        return f"ses_{self.created}"

    def send_message(self, sid, text, agent):
        if agent == "reviewer":
            m = re.search(r"当前节点：(\w+)", text)
            node = m.group(1) if m else "design"
            verdict = {"node": node, "verdict": "advance", "action": "advance",
                       "next_state": SUCC.get(node, "wrap"), "confidence": 0.9, "reason": "ok"}
            self.msgs[sid] = [Message("assistant", json.dumps(verdict))]
        else:  # developer
            self.msgs[sid] = [Message("assistant", "done work\n[WORK_DONE]")]

    def read_messages(self, sid):
        return self.msgs.get(sid, [])

    def session_status(self, sid):
        return "idle"

    def session_tokens(self, sid):
        return (0, 0)

    def abort_session(self, sid):
        pass


def _make(overrides=None):
    s = Settings(monitor_enabled=False, **(overrides or {}))
    sm = load_regime()
    client = FakeClient()
    unit = WorkflowUnit(s, sm, client, poll_sec=0.05)
    return unit, client


def _wait_result(unit, timeout=5.0):
    deadline = time.time() + timeout
    while unit.result() is None and time.time() < deadline:
        time.sleep(0.02)
    return unit.result()


def test_full_flow_completes():
    unit, client = _make()
    unit.start()
    unit.submit("实现一个反转函数")
    outcome, end, detail = _wait_result(unit)
    unit.stop()
    assert outcome == Outcome.COMPLETE
    assert end == "wrap"


def test_stop_signal_aborts():
    unit, client = _make()
    unit.start()
    unit.submit("实现一个反转函数")
    time.sleep(0.1)
    unit.deliver(_sig(unit, "constitution", SignalKind.STOP, {"reason": "test stop"}))
    outcome, end, detail = _wait_result(unit)
    unit.stop()
    assert outcome == Outcome.BLOCKED
    assert "monitor" in detail


def test_constitution_reports_emitted():
    from regime_driver.core.statechart import Bus, SignalKind, StatechartUnit

    bus = Bus()
    got = []
    cons = StatechartUnit("constitution")
    cons.register(SignalKind.REPORT, lambda s: got.append(s.payload))
    bus.register(cons)
    s = Settings(monitor_enabled=False)
    sm = load_regime()
    client = FakeClient()
    unit = WorkflowUnit(s, sm, client, poll_sec=0.05, bus=bus)
    unit.start()
    unit.submit("任务")
    deadline = time.time() + 3
    while not got and time.time() < deadline:
        time.sleep(0.02)
    unit.stop()
    assert got, "workflow never reported its session state to the constitution"
    assert got[0].get("session_id")  # report carries the alive session id


# --- interrogation / rework / convergence ---------------------------------

class ScriptedClient(FakeClient):
    """Reviewer returns a scripted sequence for ONE judge node; others default-advance."""

    def __init__(self, reviewer_script, script_node="design"):
        super().__init__()
        self.reviewer_script = list(reviewer_script)
        self.script_node = script_node
        self.reviewer_calls = 0
        self.scripted_calls = 0

    def send_message(self, sid, text, agent):
        if agent == "reviewer":
            m = re.search(r"当前节点：(\w+)", text)
            node = m.group(1) if m else "design"
            if node == self.script_node and self.reviewer_calls < len(self.reviewer_script):
                v = self.reviewer_script[self.reviewer_calls]
                self.scripted_calls += 1
            else:
                # default: advance to the node's successor
                v = {"node": node, "verdict": "advance", "action": "advance",
                     "next_state": SUCC.get(node, "wrap"), "confidence": 0.9, "reason": "ok"}
            self.reviewer_calls += 1
            self.msgs[sid] = [Message("assistant", json.dumps(v))]
        else:
            self.msgs[sid] = [Message("assistant", "rework done\n[WORK_DONE]")]


def _ask_verdict(node="design", msg="请修复"):
    return {"node": node, "verdict": "issue_pending", "action": "ask_developer",
            "message_to_developer": msg, "confidence": 0.9, "reason": msg}


def test_multiround_interrogation_converges_on_advance():
    script = [_ask_verdict("design", "fix A"),
              _ask_verdict("design", "fix B"),
              {"node": "design", "verdict": "advance", "action": "advance",
               "next_state": "implement", "confidence": 0.9, "reason": "ok"}]
    s = Settings(monitor_enabled=False, max_dialogue_rounds=5)
    sm = load_regime()
    client = ScriptedClient(script)
    unit = WorkflowUnit(s, sm, client, poll_sec=0.05)
    unit.start()
    unit.submit("任务")
    outcome, end, detail = _wait_result(unit)
    unit.stop()
    assert outcome == Outcome.COMPLETE
    assert client.scripted_calls == 3  # two reworks then advance on the design node


def test_convergence_loop_detected():
    script = [_ask_verdict("design", "same problem") for _ in range(6)]
    s = Settings(monitor_enabled=False, convergence_max_identical=2)
    sm = load_regime()
    client = ScriptedClient(script)
    unit = WorkflowUnit(s, sm, client, poll_sec=0.05)
    unit.start()
    unit.submit("任务")
    outcome, end, detail = _wait_result(unit)
    unit.stop()
    assert outcome == Outcome.BLOCKED
    assert "looping" in detail


def test_dialogue_rounds_exhausted():
    script = [_ask_verdict("design", f"fix {i}") for i in range(10)]
    s = Settings(monitor_enabled=False, max_dialogue_rounds=3)
    sm = load_regime()
    client = ScriptedClient(script)
    unit = WorkflowUnit(s, sm, client, poll_sec=0.05)
    unit.start()
    unit.submit("任务")
    outcome, end, detail = _wait_result(unit)
    unit.stop()
    assert outcome == Outcome.ERROR
    assert "dialogue rounds exhausted" in detail


def _sig(unit, src, kind, payload):
    from regime_driver.core.statechart import Signal
    return Signal(kind, src, unit.id, payload)