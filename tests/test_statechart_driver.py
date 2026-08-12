"""Tests for StatechartDriver: WorkflowUnit + WatchdogUnit on a Runtime."""

import json
import re
import time

from regime_driver.app.statechart_driver import StatechartDriver
from regime_driver.core.models import Outcome
from regime_driver.infra.regime_loader import load_regime
from regime_driver.infra.settings import Settings

SUCC = {"design": "implement", "test": "wrap"}


class Message:
    def __init__(self, role, text="", error=None, sid=None):
        self.role = role
        self.text = text
        self.error = error
        self.id = sid or f"m-{role}"


class FakeClient:
    """Scripted: developer returns [WORK_DONE]; reviewer returns a valid verdict."""

    def __init__(self, stall=False):
        self.created = 0
        self.msgs = {}
        self.status = {}
        self.stall = stall  # if True, developer never produces output (simulate stall)

    def create_session(self, title):
        self.created += 1
        return f"ses_{self.created}"

    def send_message(self, sid, text, agent):
        if agent == "reviewer":
            m = re.search(r"当前节点：(\w+)", text)
            node = m.group(1) if m else "design"
            v = {"node": node, "verdict": "advance", "action": "advance",
                 "next_state": SUCC.get(node, "wrap"), "confidence": 0.9, "reason": "ok"}
            self.msgs[sid] = [Message("assistant", json.dumps(v), sid=sid)]
        else:
            if self.stall:
                self.msgs[sid] = [Message("assistant", "thinking endlessly...", sid=sid)]
            else:
                self.msgs[sid] = [Message("assistant", "done\n[WORK_DONE]", sid=sid)]

    def read_messages(self, sid):
        return self.msgs.get(sid, [])

    def session_status(self, sid):
        return "busy" if self.stall else "idle"

    def session_tokens(self, sid):
        return (0, 0)

    def abort_session(self, sid):
        pass


def _driver(overrides=None, stall=False):
    s = Settings(monitor_enabled=False, stall_sec=2, poll_sec=0.1, **(overrides or {}))
    sm = load_regime()
    client = FakeClient(stall=stall)
    d = StatechartDriver(s, sm, client, enforce_invariants=True)
    return d


def test_statechart_driver_full_flow():
    d = _driver()
    outcome, end, detail = d.run("实现反转函数")
    assert outcome == Outcome.COMPLETE
    assert end == "wrap"


def test_statechart_driver_stall_triggers_watchdog_stop():
    # stall=True: developer never produces [WORK_DONE]; watchdog should STOP
    d = _driver(stall=True)
    outcome, end, detail = d.run("实现反转函数")
    assert outcome == Outcome.BLOCKED
    assert "monitor" in (detail or "")


def test_statechart_driver_accepts_custom_watchdog():
    from regime_driver.app.statechart_runtime import ThreadedUnit
    from regime_driver.core.statechart import SignalKind

    class AlwaysStopWatchdog(ThreadedUnit):
        def __init__(self):
            super().__init__("watchdog", None, role="watchdog")
            self.register(SignalKind.REPORT, self._r)
            self.register(SignalKind.STOP, lambda s: None)  # I2

        def _r(self, sig):
            self.send("workflow", SignalKind.STOP, {"reason": "custom always-stop"})

    s = Settings(monitor_enabled=False, poll_sec=0.1)
    sm = load_regime()
    client = FakeClient()
    d = StatechartDriver(s, sm, client, watchdog=AlwaysStopWatchdog(),
                         enforce_invariants=True)
    outcome, end, detail = d.run("任务")
    assert outcome == Outcome.BLOCKED
    assert "custom always-stop" in (detail or "")