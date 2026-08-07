"""Tests for deep static validation (core/validate.py)."""

from __future__ import annotations

import json
from pathlib import Path

from regime_driver.core.models import Regime
from regime_driver.core.role import RoleRegistry, Role, developer_policy
from regime_driver.core.state_machine import StateMachine
from regime_driver.core.validate import deep_validate


def _flow(entry: str, start: str, nodes: dict) -> str:
    return json.dumps({
        "version": "test",
        "flows": {entry: {"nodes": nodes}},
        "entry": {"flow": entry, "start_node": start},
    })


def _node(node_id: str, **kw) -> dict:
    d = {"id": node_id, "desc": "n", "type": "agent", "role": "developer"}
    d.update(kw)
    return d


def make_sm(raw: str) -> StateMachine:
    return StateMachine(Regime.model_validate(json.loads(raw)))


def test_clean_flow_passes() -> None:
    raw = _flow("f", "a", {
        "a": _node("a", next="b"),
        "b": _node("b"),
    })
    res = deep_validate(make_sm(raw))
    assert res.ok
    assert res.errors == []


def test_unknown_role_detected() -> None:
    raw = _flow("f", "a", {"a": _node("a", role="nonexistent")})
    res = deep_validate(make_sm(raw))
    assert not res.ok
    assert any("role" in e for e in res.errors)


def test_unloadable_skill_detected() -> None:
    raw = _flow("f", "a", {"a": _node("a", skill="no_such_skill")})
    res = deep_validate(
        make_sm(raw),
        load_skill=lambda name: (_ for _ in ()).throw(RuntimeError(f"skill '{name}' not found")),
    )
    assert not res.ok
    assert any("skill" in e for e in res.errors)


def test_unknown_tool_detected() -> None:
    raw = _flow("f", "a", {"a": _node("a", type="tool", tool="nope")})
    res = deep_validate(make_sm(raw))
    assert not res.ok
    assert any("tool" in e for e in res.errors)


def test_unreachable_island_warns() -> None:
    raw = _flow("f", "a", {
        "a": _node("a"),
        "orphan": _node("orphan"),
    })
    res = deep_validate(make_sm(raw))
    assert res.ok
    assert any("unreachable" in w for w in res.warnings)


def test_spine_cycle_detected() -> None:
    raw = _flow("f", "a", {
        "a": _node("a", next="b"),
        "b": _node("b", next="a"),
    })
    res = deep_validate(make_sm(raw))
    assert not res.ok
    assert any("cycle" in e for e in res.errors)


def test_custom_roles_registry() -> None:
    roles = RoleRegistry().register(
        Role(id="auditor", agent="auditor", policy=developer_policy(), description="a"))
    raw = _flow("f", "a", {"a": _node("a", role="auditor")})
    res = deep_validate(make_sm(raw), roles=roles)
    assert res.ok
