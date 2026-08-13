"""Tests for offline preflight trial run (app/preflight.py)."""

from __future__ import annotations

import json

from regime_driver.app.preflight import preflight
from regime_driver.core.models import Regime
from regime_driver.core.state_machine import StateMachine


def _sm(raw: str) -> StateMachine:
    return StateMachine(Regime.model_validate(json.loads(raw)))


def _flow(nodes: dict) -> StateMachine:
    return _sm(json.dumps({
        "version": "t",
        "flows": {"f": {"nodes": nodes}},
        "entry": {"flow": "f", "start_node": "a"},
    }))


def _node(nid: str, **kw) -> dict:
    d = {"id": nid, "desc": "n", "type": "agent", "role": "developer"}
    d.update(kw)
    return d


def test_clean_flow_completes() -> None:
    sm = _flow({"a": _node("a", next="b"), "b": _node("b")})
    res = preflight(sm, timeout_sec=10)
    assert res["ok"] is True
    assert res["outcome"] == "complete"


def test_judge_terminal_flow_completes() -> None:
    # regression: a flow whose LAST node is a judge (final review) must complete
    # (advance with next_state=null), not exhaust the reviewer gate.
    sm = _flow({
        "a": _node("a", next="j"),
        "j": _node("j", type="judge", role="reviewer"),
    })
    res = preflight(sm, timeout_sec=10)
    assert res["ok"] is True, res
    assert res["outcome"] == "complete"
    assert res["end"] == "j"


def test_stall_fault_blocks() -> None:
    sm = _flow({"a": _node("a", next="b"), "b": _node("b")})
    res = preflight(sm, fault="stall", timeout_sec=10, stall_sec=1)
    assert res["ok"] is False
    assert res["outcome"] in ("blocked", "error")


def test_unknown_fault_rejected() -> None:
    sm = _flow({"a": _node("a")})
    res = preflight(sm, fault="bogus")
    assert res["ok"] is False
    assert "unknown fault" in res["detail"]


def test_returns_json_serializable() -> None:
    sm = _flow({"a": _node("a")})
    res = preflight(sm, timeout_sec=10)
    json.dumps(res)  # must not raise


def test_preflight_delay_long_generation_not_false_stalled():
    """A slow-but-streaming generation (delay rule) must COMPLETE, not stall.

    WORK_PLAN10 regression: a long single-step generation reports busy the whole
    time while token counts stay 0. Liveness must come from SSE activity (which
    the mock emits for a `delay` session), so the watchdog must NOT misclassify
    a slow streaming session as a stall.
    """
    from regime_driver.testing import MockClient
    from regime_driver.app.statechart_driver import StatechartDriver
    from regime_driver.infra.regime_loader import load_regime
    from regime_driver.infra.settings import Settings
    from regime_driver.core.models import Outcome

    sm = load_regime()
    client = MockClient(sm=sm)
    # a slow-but-streaming generation: delay clearly exceeds the watchdog stall
    # window, but the session is busy AND streaming (emits SSE deltas) the whole
    # time, so it must NOT be misclassified as a stall.
    start = getattr(sm, "start", None)
    client.rule(sm.node(start).role, start, delay=1.5)
    settings = Settings(monitor_enabled=False, poll_sec=0.1, stall_sec=1)
    driver = StatechartDriver(settings, sm, client, enforce_invariants=True)
    outcome, end, detail = driver.run("长思考任务", timeout_sec=20.0)
    assert outcome == Outcome.COMPLETE, f"slow streaming must not stall: {detail}"
    assert end == "wrap"
