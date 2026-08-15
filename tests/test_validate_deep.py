"""Tests for deep static validation (core/validate.py)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from regime_driver.core.models import Regime
from regime_driver.core.role import RoleRegistry, Role, developer_policy
from regime_driver.core.state_machine import StateMachine, StateMachineError
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


def test_verify_on_non_judge_detected() -> None:
    """WORK_PLAN13: `verify` on a non-judge node is dead config — fail loudly."""
    raw = _flow("f", "a", {"a": _node("a", verify="docker exec {container} pytest -q")})
    res = deep_validate(make_sm(raw))
    assert not res.ok
    assert any("verify" in e for e in res.errors)


def test_verify_on_judge_allowed() -> None:
    raw = _flow("f", "a", {"a": _node("a", type="judge", role="reviewer",
                                      verify="docker exec {container} pytest -q", next=None)})
    res = deep_validate(make_sm(raw))
    assert res.ok, res.errors


def test_verify_whitelist_shape_enforced() -> None:
    # a verify command outside the docker-exec whitelist shape is rejected at
    # StateMachine CONSTRUCTION (the single point every flow source passes
    # through — store / file / registry / design), so a store-residual
    # `sg docker -c` wrapper (the 2026-08-14 nightly) can never reach a run.
    raw = _flow("f", "a", {"a": _node("a", type="judge", role="reviewer",
                                      verify="sg docker -c \"docker exec {container} bash -c 'pytest'\"",
                                      next=None)})
    with pytest.raises(StateMachineError) as ei:
        make_sm(raw)
    assert "whitelist" in str(ei.value)


def test_readonly_on_judge_detected() -> None:
    raw = _flow("f", "a", {"a": _node("a", type="judge", role="reviewer",
                                      readonly=True, next=None)})
    res = deep_validate(make_sm(raw))
    assert not res.ok
    assert any("readonly" in e for e in res.errors)


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


def test_branch_rework_loop_warns() -> None:
    raw = _flow("f", "a", {
        "a": _node("a", next="b"),
        "b": _node("b", branches=[{"when": "x", "goto": "a"}]),
    })
    res = deep_validate(make_sm(raw))
    assert res.ok  # rework loop is a warning, not an error
    assert any("rework loop" in w for w in res.warnings)


def test_custom_roles_registry() -> None:
    roles = RoleRegistry().register(
        Role(id="auditor", agent="auditor", policy=developer_policy(), description="a"))
    raw = _flow("f", "a", {"a": _node("a", role="auditor")})
    res = deep_validate(make_sm(raw), roles=roles)
    assert res.ok
