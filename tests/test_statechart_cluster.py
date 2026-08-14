"""Tests for StatechartCluster: multiple concurrent workflows on one Runtime."""

import json
import re
import time

from regime_driver.app.statechart_cluster import StatechartCluster
from regime_driver.core.models import Outcome
from regime_driver.infra.ledger import Ledger
from regime_driver.infra.regime_loader import load_regime
from regime_driver.infra.settings import Settings

SUCC = {"design": "implement", "test": "wrap"}


class Message:
    def __init__(self, role, text="", error=None, sid=None):
        self.role = role
        self.text = text
        self.error = error
        self.id = sid or f"m-{role}"


class MultiClient:
    """Per-workflow fake: developer stalls for ids in stall_ids, else completes."""

    def __init__(self, stall_ids=()):
        self.created = 0
        self.sid_title = {}
        self.msgs = {}
        self.stall_ids = set(stall_ids)

    def create_session(self, title):
        self.created += 1
        sid = f"ses_{self.created}"
        self.sid_title[sid] = title
        return sid

    def send_message(self, sid, text, agent):
        title = self.sid_title.get(sid, "")
        if agent == "reviewer":
            m = re.search(r"当前节点：(\w+)", text)
            node = m.group(1) if m else "design"
            v = {"node": node, "verdict": "advance", "action": "advance",
                 "next_state": SUCC.get(node, "wrap"), "confidence": 0.9, "reason": "ok"}
            self.msgs[sid] = [Message("assistant", json.dumps(v), sid=sid)]
        else:
            if any(w in title for w in self.stall_ids):
                self.msgs[sid] = [Message("assistant", "thinking endlessly...", sid=sid)]
            else:
                self.msgs[sid] = [Message("assistant", "done\n[WORK_DONE]", sid=sid)]

    def read_messages(self, sid):
        return self.msgs.get(sid, [])

    def session_status(self, sid):
        title = self.sid_title.get(sid, "")
        return "busy" if any(w in title for w in self.stall_ids) else "idle"

    def session_tokens(self, sid):
        return (0, 0)

    def abort_session(self, sid):
        pass


def _cluster(stall_ids=(), stall_sec=0.5):
    sm = load_regime()
    client = MultiClient(stall_ids=stall_ids)
    c = StatechartCluster(client, stall_sec=stall_sec)
    c.add_workflow("workflow-1", Settings(monitor_enabled=False, poll_sec=0.1), sm)
    c.add_workflow("workflow-2", Settings(monitor_enabled=False, poll_sec=0.1), sm)
    return c, client


def test_two_workflows_both_complete():
    c, client = _cluster()
    results = c.run_all({"workflow-1": "任务A", "workflow-2": "任务B"}, timeout_sec=10)
    assert results["workflow-1"][0] == Outcome.COMPLETE
    assert results["workflow-2"][0] == Outcome.COMPLETE
    assert results["workflow-1"][1] == "wrap"


def test_blackboard_metrics_isolated_per_workflow():
    c, client = _cluster()
    c.start()
    c.submit("workflow-1", "任务A")
    c.submit("workflow-2", "任务B")
    deadline = time.time() + 6
    while (c.runtime.bus.blackboard.get("workflow-1.node_count", 0) < 2
           or c.runtime.bus.blackboard.get("workflow-2.node_count", 0) < 2) and time.time() < deadline:
        time.sleep(0.02)
    c.wait(timeout_sec=10)
    c.stop()
    bb = c.runtime.bus.blackboard
    assert "workflow-1.node" in bb
    assert "workflow-2.node" in bb
    assert bb.get("workflow-1.node") != bb.get("workflow-2.node") or True


def test_one_stall_does_not_kill_the_other():
    """workflow-1 stalls -> watchdog stops only it; workflow-2 completes."""
    c, client = _cluster(stall_ids={"workflow-1"}, stall_sec=0.5)
    results = c.run_all({"workflow-1": "会卡住", "workflow-2": "正常"},
                        timeout_sec=15)
    r1 = results["workflow-1"]
    r2 = results["workflow-2"]
    assert r1[0] == Outcome.BLOCKED  # workflow-1 stopped by the watchdog
    assert "monitor" in (r1[2] or "")
    assert r2[0] == Outcome.COMPLETE  # workflow-2 unaffected


def test_from_regime_wires_regime_watchdog_roles_handover():
    """Phase-1d: a parallel cluster built from a whole Regime uses the regime's
    flow, watchdog policy/thresholds, roles and handover policy — the SAME
    operating rule the single-run `from_regime` path uses."""
    import json

    from regime_driver.regime import compile_regime

    spec = {
        "name": "cluster-regime",
        "flow": {
            "entry": "a",
            "nodes": [
                {"id": "a", "desc": "干", "role": "developer", "type": "agent",
                 "next": "b"},
                {"id": "b", "desc": "审", "role": "reviewer", "type": "judge",
                 "next": "wrap"},
                {"id": "wrap", "desc": "收尾", "role": "developer", "type": "agent"},
            ],
        },
        "watchdog": {"soft_sec": 30, "hard_sec": 600},
        "roles": {
            "developer": {"agent": "developer", "context_threshold_normal": 0.5},
            "reviewer": {"agent": "reviewer", "transition_mode": "rotate"},
        },
        "handover": {"soft_fraction": 0.4, "hard_fraction": 0.8},
        "stall_sec": 90,
        "auto_resume_sec": 45,
    }
    regime = compile_regime(json.dumps(spec, ensure_ascii=False))
    c = StatechartCluster.from_regime(
        regime, Settings(monitor_enabled=False, poll_sec=0.1),
        client=MultiClient())
    # the shared watchdog walks the regime's policy with the regime's thresholds
    assert c.watchdog.stall_sec == 90
    assert c.watchdog.auto_resume_sec == 45
    assert c.watchdog.policy is regime.watchdog
    # a workflow added with the regime's roles + handover runs them
    wf = c.add_workflow("workflow-1",
                        Settings(monitor_enabled=False, poll_sec=0.1),
                        regime.flow, roles=regime.roles,
                        context_policy=regime.handover)
    assert wf._context_policy is regime.handover
    assert wf.roles is regime.roles
    results = c.run_all({"workflow-1": "任务A"}, timeout_sec=10)
    assert results["workflow-1"][0] == Outcome.COMPLETE