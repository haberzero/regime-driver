"""Tests for the shared Blackboard (global state) + its pub/sub change events."""

import threading
import time

from regime_driver.app.blackboard import Blackboard, CHANGED_EVENT
from regime_driver.app.statechart_runtime import Runtime, ThreadedUnit
from regime_driver.core.statechart import Bus


def test_blackboard_get_set_snapshot():
    bb = Blackboard()
    bb.set("a", 1)
    bb.update(b=2, c=3)
    assert bb.get("a") == 1
    assert bb.get("missing", "x") == "x"
    assert bb.snapshot() == {"a": 1, "b": 2, "c": 3}
    assert "b" in bb


def test_blackboard_thread_safe_writes():
    bb = Blackboard()
    errors = []

    def writer(i):
        try:
            for j in range(200):
                bb.set(f"k{i}_{j}", j)
        except Exception as e:  # pragma: no cover
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert bb.get("k3_199") == 199


def test_blackboard_change_publishes_event():
    bus = Bus()
    got = []
    obs = type("O", (), {"handle_event": lambda self, e, f: got.append((e, f))})()
    from regime_driver.core.statechart import StatechartUnit
    obs = StatechartUnit("obs", bus=bus)
    obs.on_event(CHANGED_EVENT, lambda f: got.append(f))
    obs.subscribe(CHANGED_EVENT)
    bus.register(obs)
    bb = Blackboard(publisher=lambda event, fields: bus.publish("blackboard", event, fields))
    bus.blackboard = bb
    bb.set("workflow.node", "design")
    assert got and got[0]["key"] == "workflow.node" and got[0]["value"] == "design"


def test_runtime_attaches_blackboard_and_publishes():
    rt = Runtime(enforce_invariants=False)
    assert rt.bus.blackboard is not None
    got = []
    obs = ThreadedUnit("obs")
    obs.on_event(CHANGED_EVENT, lambda f: got.append(f))
    rt.register(obs)  # register first: sets obs.bus so subscribe() registers
    obs.subscribe(CHANGED_EVENT)
    rt.start()
    rt.bus.blackboard.set("workflow.node", "implement")
    deadline = time.time() + 3
    while not got and time.time() < deadline:
        pass
    rt.stop()
    assert got and got[0]["value"] == "implement"


def test_workflow_writes_metrics_to_blackboard():
    """The workflow publishes live node/phase metrics to the shared blackboard."""
    from regime_driver.app.workflow_unit import WorkflowUnit
    from regime_driver.infra.regime_loader import load_regime
    from regime_driver.infra.settings import Settings

    rt = Runtime(enforce_invariants=False)
    s = Settings(monitor_enabled=False, poll_sec=0.1)
    sm = load_regime()
    client = _FakeClient()
    unit = WorkflowUnit(s, sm, client, poll_sec=0.1, bus=rt.bus)
    rt.register(unit)
    rt.start()
    unit.submit("任务")
    deadline = time.time() + 3
    while rt.bus.blackboard.get("workflow.node_count", 0) < 2 and time.time() < deadline:
        time.sleep(0.02)
    rt.stop()
    assert rt.bus.blackboard.get("workflow.node") is not None
    assert rt.bus.blackboard.get("workflow.node_count", 0) >= 2


class Message:
    def __init__(self, role, text="", error=None):
        self.role = role
        self.text = text
        self.error = error


import json
import re


class _FakeClient:
    def __init__(self):
        self.created = 0
        self.msgs = {}

    def create_session(self, title):
        self.created += 1
        return f"ses_{self.created}"

    def send_message(self, sid, text, agent):
        if agent == "reviewer":
            m = re.search(r"当前节点：(\w+)", text)
            node = m.group(1) if m else "design"
            target = {"design": "implement", "test": "wrap"}.get(node, "wrap")
            v = {"node": node, "verdict": "advance", "action": "advance",
                 "next_state": target, "confidence": 0.9, "reason": "ok"}
            self.msgs[sid] = [Message("assistant", json.dumps(v))]
        else:
            self.msgs[sid] = [Message("assistant", "done\n[WORK_DONE]")]

    def read_messages(self, sid):
        return self.msgs.get(sid, [])

    def session_status(self, sid):
        return "idle"

    def session_tokens(self, sid):
        return (0, 0)

    def abort_session(self, sid):
        pass