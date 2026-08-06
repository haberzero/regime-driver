"""Tests for Telemetry (visualization on pub/sub + blackboard)."""

import time

from regime_driver.app.blackboard import Blackboard
from regime_driver.app.statechart_cluster import StatechartCluster
from regime_driver.app.statechart_runtime import Runtime, ThreadedUnit
from regime_driver.app.telemetry import Telemetry
from regime_driver.core.statechart import Bus, SignalKind, StatechartUnit


def test_telemetry_captures_watchdog_events():
    bus = Bus()
    obs = Telemetry(bus=bus)
    maker = StatechartUnit("constitution", bus=bus)
    bus.register(obs).register(maker)
    maker.emit("watchdog_fire", kind="stall", session="s1", detail="no progress")
    assert len(obs.recent_watchdog()) == 1
    assert obs.recent_watchdog()[0]["kind"] == "stall"


def test_telemetry_reads_blackboard_workflows():
    bus = Bus()
    bb = Blackboard(publisher=lambda ev, f: bus.publish("blackboard", ev, f))
    bus.blackboard = bb
    obs = Telemetry(bus=bus)
    bus.register(obs)
    bb.update(**{"workflow-1.node": "design", "workflow-1.state": "running",
                 "workflow-2.node": "implement", "workflow-2.state": "running"})
    status = obs.workflow_status()
    assert status["workflow-1"]["node"] == "design"
    assert status["workflow-2"]["state"] == "running"


def test_telemetry_render_contains_workflows():
    bus = Bus()
    bb = Blackboard(publisher=lambda ev, f: bus.publish("blackboard", ev, f))
    bus.blackboard = bb
    obs = Telemetry(bus=bus)
    bus.register(obs)
    bb.set("workflow-1.node", "wrap")
    text = obs.render()
    assert "workflow-1" in text
    assert "workflow status" in text


def test_telemetry_in_cluster():
    """A telemetry unit can be registered in a cluster and observe concurrency."""
    from regime_driver.infra.regime_loader import load_regime
    from regime_driver.infra.settings import Settings

    sm = load_regime()
    client = _ClusterFake()
    c = StatechartCluster(client)
    obs = Telemetry(bus=c.runtime.bus)
    c.runtime.bus.register(obs)  # telemetry is a StatechartUnit: attach to bus, not runtime
    c.add_workflow("wf-a", Settings(monitor_enabled=False, poll_sec=0.1), sm)
    c.add_workflow("wf-b", Settings(monitor_enabled=False, poll_sec=0.1), sm)
    c.run_all({"wf-a": "A", "wf-b": "B"}, timeout_sec=10)
    status = obs.workflow_status()
    assert "wf-a" in status or "wf-b" in status
    assert obs.render()


class _ClusterFake:
    def __init__(self):
        self.created = 0
        self.sid_title = {}
        self.msgs = {}

    def create_session(self, title):
        self.created += 1
        sid = f"ses_{self.created}"
        self.sid_title[sid] = title
        return sid

    def send_message(self, sid, text, agent):
        import json
        import re
        if agent == "reviewer":
            m = re.search(r"当前节点：(\w+)", text)
            node = m.group(1) if m else "design"
            target = {"design": "implement", "test": "wrap"}.get(node, "wrap")
            self.msgs[sid] = [_Msg("assistant", json.dumps(
                {"node": node, "verdict": "advance", "action": "advance",
                 "next_state": target, "confidence": 0.9, "reason": "ok"}))]
        else:
            self.msgs[sid] = [_Msg("assistant", "done\n[WORK_DONE]")]

    def read_messages(self, sid):
        return self.msgs.get(sid, [])

    def session_status(self, sid):
        return "idle"

    def session_tokens(self, sid):
        return (0, 0)

    def abort_session(self, sid):
        pass


class _Msg:
    def __init__(self, role, text="", error=None):
        self.role = role
        self.text = text
        self.error = error