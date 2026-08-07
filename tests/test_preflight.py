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


def test_stall_fault_blocks() -> None:
    sm = _flow({"a": _node("a", next="b"), "b": _node("b")})
    res = preflight(sm, fault="stall", timeout_sec=10)
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
