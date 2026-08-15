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


def test_scale_timeout_grows_with_node_count():
    """Long flows (10+ nodes) need a bigger offline-trial budget than 30s."""
    from regime_driver.app.preflight import _scale_timeout
    assert _scale_timeout(1) == 30.0      # floor for tiny flows
    assert _scale_timeout(3) == 30.0      # floor still applies below 8s/node
    assert _scale_timeout(6) == 48.0      # 6-node default flow: 8s/node
    assert _scale_timeout(11) == 88.0     # 11-node night flow
    assert _scale_timeout(20) == 160.0


def test_preflight_default_timeout_scales_with_flow_size():
    """preflight() with the default (None) timeout must survive a long flow."""
    nodes = {f"n{i}": _node(f"n{i}", next=f"n{i+1}" if i < 10 else None)
             for i in range(11)}
    sm = _sm(json.dumps({
        "version": "t",
        "flows": {"f": {"nodes": nodes}},
        "entry": {"flow": "f", "start_node": "n0"},
    }))
    res = preflight(sm)  # no explicit timeout -> node-count-scaled budget
    assert res["ok"] is True, res
    assert res["outcome"] == "complete"


def test_hyphenated_node_ids_complete_preflight():
    """Node ids with hyphens (test-core, impl-api) must not break the offline
    trial: MockClient's node-id parser used to truncate at '-' (\w+), turning
    'test-core' into 'test' and failing any non-template flow id scheme."""
    nodes = {
        "understand": _node("understand", next="design"),
        "design": _node("design", role="reviewer", type="judge", next="impl-core"),
        "impl-core": _node("impl-core", next="test-core"),
        "test-core": _node("test-core", role="reviewer", type="judge", next="impl-api"),
        "impl-api": _node("impl-api", next="test-api"),
        "test-api": _node("test-api", role="reviewer", type="judge", next="wrap"),
        "wrap": _node("wrap"),
    }
    sm = _sm(json.dumps({
        "version": "t",
        "flows": {"f": {"nodes": nodes}},
        "entry": {"flow": "f", "start_node": "understand"},
    }))
    res = preflight(sm, timeout_sec=60)
    assert res["ok"] is True, res
    assert res["outcome"] == "complete"


def test_preflight_timeout_retried_once_with_doubled_budget():
    """A trial wall-clock expiry is retried once with 2x budget (best-effort
    recovery) before giving up; a second expiry still fails honestly."""
    import regime_driver.app.preflight as pf

    calls = []

    class FlakyDriver:
        def __init__(self, *a, **kw):
            pass
        def run(self, context, timeout_sec=None):
            calls.append(timeout_sec)
            if len(calls) == 1:
                from regime_driver.core.models import Outcome
                return (Outcome.ERROR, "impl-core", "run timed out")
            from regime_driver.core.models import Outcome
            return (Outcome.COMPLETE, "wrap", None)

    orig = pf.StatechartDriver
    pf.StatechartDriver = FlakyDriver
    try:
        res = pf.preflight(_flow({"a": _node("a")}), timeout_sec=30.0)
    finally:
        pf.StatechartDriver = orig
    assert res["ok"] is True, res
    assert calls == [30.0, 60.0], f"expected one retry with doubled budget, got {calls}"
