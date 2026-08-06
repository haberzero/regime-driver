"""Tests for the reusable offline MockClient (regime_driver.testing)."""

import json
import time

from regime_driver.app.statechart_driver import StatechartDriver
from regime_driver.app.workflow_unit import WorkflowUnit
from regime_driver.core.models import Outcome
from regime_driver.infra.regime_loader import load_regime
from regime_driver.infra.settings import Settings
from regime_driver.testing import MockClient, MockRule


def _workflow(client, **overrides):
    s = Settings(monitor_enabled=False, poll_sec=0.1, **overrides)
    return WorkflowUnit(s, load_regime(), client, poll_sec=0.05)


def _wait(unit, timeout=5.0):
    deadline = time.time() + timeout
    while unit.result() is None and time.time() < deadline:
        time.sleep(0.02)
    return unit.result()


def test_mock_full_flow_offline_completes():
    """MockClient drives a full workflow to COMPLETE with no network."""
    unit = _workflow(MockClient(sm=load_regime()))
    unit.start()
    unit.submit("实现反转函数")
    outcome, end, _ = _wait(unit)
    unit.stop()
    assert outcome == Outcome.COMPLETE
    assert end == "wrap"


def test_mock_driver_offline_completes():
    d = StatechartDriver(Settings(monitor_enabled=False, poll_sec=0.1), load_regime(),
                         MockClient(sm=load_regime()), enforce_invariants=True)
    outcome, _, _ = d.run("任务")
    assert outcome == Outcome.COMPLETE


def test_mock_rule_delay_observed():
    c = MockClient(sm=load_regime())
    c.rule("reviewer", "design", delay=0.3)
    unit = _workflow(c)
    t0 = time.monotonic()
    unit.start()
    unit.submit("task")
    _wait(unit)
    unit.stop()
    assert time.monotonic() - t0 >= 0.3


def test_mock_rule_stall_triggers_constitution_stop():
    c = MockClient(sm=load_regime())
    c.rule("developer", "understand", stall=True)
    d = StatechartDriver(Settings(monitor_enabled=False, poll_sec=0.1, stall_sec=1),
                         load_regime(), c, enforce_invariants=True)
    outcome, _, detail = d.run("会卡住")
    assert outcome == Outcome.BLOCKED
    assert "monitor" in (detail or "")


def test_mock_messages_accumulate_not_replace():
    """The mock appends to history (like the real client), preserving the
    stale-text judge scenario the real accumulation causes."""
    c = MockClient(sm=load_regime())
    sid = c.create_session("s")
    c.send_message(sid, "当前节点：design — 方案", "reviewer")
    c.send_message(sid, "当前节点：design — 重判", "reviewer")
    msgs = c.read_messages(sid)
    assert len(msgs) == 2  # accumulated, not replaced
    assert all(m.role == "assistant" for m in msgs)
    assert msgs[0].completed and msgs[1].completed


def test_mock_rule_matcher_specific_over_generic():
    c = MockClient(sm=load_regime())
    c.rule("reviewer", None, reply="generic")
    c.rule("reviewer", "design", reply="specific")
    assert c._rule_for("reviewer", "design").reply == "specific"
    assert c._rule_for("reviewer", "test").reply == "generic"


def test_mock_error_rule_emits_error_message():
    c = MockClient(sm=load_regime())
    c.rule("developer", "understand", error="boom")
    sid = c.create_session("s")
    c.send_message(sid, "当前节点：understand", "developer")
    assert c.read_messages(sid)[0].error == "boom"