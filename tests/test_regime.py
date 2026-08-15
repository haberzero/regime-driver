"""Tests for the Regime first-class object (WORK_PLAN14 阶段 1).

The whole operating rule (flow + roles + watchdog + handover) compiles through
one gate, persists under one named source of truth, and drives the runtime.
"""

from __future__ import annotations

import json

import pytest

from regime_driver.app.statechart_driver import StatechartDriver
from regime_driver.core.models import Outcome
from regime_driver.core.role import RoleRegistry
from regime_driver.core.state_machine import StateMachine
from regime_driver.flow import FlowError
from regime_driver.infra.settings import Settings
from regime_driver.regime import (
    Regime,
    RegimeEntry,
    RegimeRegistry,
    compile_regime,
    validate_regime,
)
from regime_driver.testing import MockClient


def _flow_spec():
    return {
        "entry": "a",
        "nodes": [
            {"id": "a", "desc": "干", "role": "developer", "type": "agent", "next": "b"},
            {"id": "b", "desc": "审", "role": "reviewer", "type": "judge"},
        ],
    }


def _full_spec(**overrides):
    spec = {
        "name": "my-regime",
        "description": "test",
        "flow": _flow_spec(),
        "roles": {
            "developer": {"agent": "developer", "context_threshold_normal": 0.5},
            "reviewer": {"agent": "reviewer", "transition_mode": "rotate"},
        },
        "watchdog": {"soft_sec": 30, "hard_sec": 600},
        "handover": {"soft_fraction": 0.4, "hard_fraction": 0.8},
        "stall_sec": 90,
        "auto_resume_sec": 45,
    }
    spec.update(overrides)
    return json.dumps(spec, ensure_ascii=False)


# -- compile ------------------------------------------------------------------


def test_compile_regime_full_components():
    r = compile_regime(_full_spec())
    assert r.name == "my-regime"
    assert isinstance(r.flow, StateMachine)
    assert r.flow.flow_name == "my-regime"
    assert r.roles is not None and r.roles.has("developer") and r.roles.has("reviewer")
    assert r.roles.get("developer").policy.context_threshold_normal == 0.5
    assert r.roles.get("reviewer").policy.transition_mode.value == "rotate"
    assert r.watchdog is not None and r.watchdog.name == "operator"
    assert r.handover is not None and r.handover.soft_fraction == 0.4
    assert r.stall_sec == 90
    assert r.auto_resume_sec == 45


def test_compile_regime_minimal_flow_only():
    r = compile_regime(_full_spec(roles=None, watchdog=None, handover=None,
                                  stall_sec=None, auto_resume_sec=None))
    assert r.roles is None
    assert r.watchdog is None
    assert r.handover is None
    assert r.stall_sec is None


def test_compile_regime_requires_flow():
    with pytest.raises(FlowError):
        compile_regime(json.dumps({"name": "x", "roles": {}}))


def test_compile_regime_rejects_bad_watchdog():
    with pytest.raises(FlowError):
        compile_regime(_full_spec(watchdog={"soft_sec": -1}))
    with pytest.raises(FlowError):
        compile_regime(_full_spec(watchdog={"soft_sec": "x"}))


def test_compile_regime_rejects_bad_handover():
    with pytest.raises(FlowError):
        compile_regime(_full_spec(handover={"soft_fraction": 0.9, "hard_fraction": 0.5}))


def test_compile_regime_rejects_bad_roles():
    with pytest.raises(FlowError):
        compile_regime(_full_spec(roles={"developer": {"transition_mode": "explode"}}))


def test_compile_regime_rejects_bad_threshold():
    with pytest.raises(FlowError):
        compile_regime(_full_spec(stall_sec="not-a-number"))
    with pytest.raises(FlowError):
        compile_regime(_full_spec(stall_sec=-10))
    with pytest.raises(FlowError):
        compile_regime(_full_spec(auto_resume_sec=-5))


def test_compile_regime_rejects_non_dict_role():
    with pytest.raises(FlowError):
        compile_regime(_full_spec(roles={"developer": "developer"}))


def test_compile_regime_rejects_unknown_role_field():
    with pytest.raises(FlowError):
        compile_regime(_full_spec(roles={
            "developer": {"agent": "developer", "context_thresold_normal": 0.9}}))


def test_compile_regime_rejects_empty_handover():
    # an empty handover object would silently enable the default policy
    with pytest.raises(FlowError):
        compile_regime(_full_spec(handover={}))


def test_compile_regime_rejects_unsafe_name():
    with pytest.raises(FlowError):
        compile_regime(_full_spec(name="../evil"))


def test_compile_regime_rejects_bool_watchdog_threshold():
    # bool is an int subclass; a boolean threshold must be rejected, not treated
    # as a 1-second value
    with pytest.raises(FlowError):
        compile_regime(_full_spec(watchdog={"soft_sec": True}))


# -- validate -----------------------------------------------------------------


def test_validate_regime_unregistered_role_rejected():
    spec = _full_spec(roles=None)
    spec = json.loads(spec)
    spec["flow"] = {
        "entry": "a",
        "nodes": [
            {"id": "a", "desc": "干", "role": "ghost", "type": "agent"},
        ],
    }
    r = compile_regime(json.dumps(spec, ensure_ascii=False))
    res = validate_regime(r)
    assert not res.ok
    assert any("not registered" in e for e in res.errors)


def test_validate_regime_ok_with_roles():
    r = compile_regime(_full_spec())
    res = validate_regime(r)
    assert res.ok, res.errors


# -- round-trip ---------------------------------------------------------------


def test_regime_to_dict_roundtrip():
    r = compile_regime(_full_spec())
    d = r.to_dict()
    r2 = Regime.from_dict(d)
    assert r2.name == r.name
    assert r2.flow.flow_name == r.flow.flow_name
    assert list(r2.flow.flow_path()) == list(r.flow.flow_path())
    assert r2.roles.ids() == r.roles.ids()
    assert r2.watchdog is not None and r2.handover is not None
    assert r2.stall_sec == r.stall_sec and r2.auto_resume_sec == r.auto_resume_sec


def test_regime_watchdog_policy_roundtrips_exactly():
    """The serialized watchdog policy must survive to_dict -> from_dict with the
    exact soft/hard thresholds, action and meta-gate flag (W3)."""
    r = compile_regime(_full_spec(watchdog={
        "soft_sec": 33, "soft_action": "interrupt", "meta_gate_soft": True,
        "hard_sec": 720}))
    d = r.to_dict()
    r2 = Regime.from_dict(d)
    p2 = r2.watchdog
    assert p2 is not None
    actions = {}
    seconds = {}
    for rule in p2.rules:
        f = getattr(rule.predicate, "__closure__", None)
        sec = [c.cell_contents for c in f
               if isinstance(c.cell_contents, (int, float))
               and not isinstance(c.cell_contents, bool)]
        seconds[rule.action] = float(sec[0])
        actions[rule.action] = rule.meta
    assert seconds["interrupt"] == 33
    assert seconds["kill"] == 720
    assert actions["interrupt"] is True


# -- registry -----------------------------------------------------------------


def test_regime_registry_register_and_query(tmp_path):
    reg = RegimeRegistry(store_dir=tmp_path / "store")
    entry = reg.register(compile_regime(_full_spec()), validate=True)
    assert isinstance(entry, RegimeEntry)
    assert reg.get("my-regime").regime.name == "my-regime"
    assert reg.regime("my-regime") is not None
    assert [e.name for e in reg.list()] == ["my-regime"]


def test_regime_registry_persists_and_reloads(tmp_path):
    store = tmp_path / "store"
    reg = RegimeRegistry(store_dir=store)
    reg.register(compile_regime(_full_spec()), validate=True)
    # a second registry (separate CLI invocation) sees the persisted regime
    reg2 = RegimeRegistry(store_dir=store)
    assert reg2.regime("my-regime") is not None
    v1 = reg2.get("my-regime").version
    entry = reg2.reload("my-regime")
    assert entry.version > v1


def test_regime_registry_reload_failure_preserves_current(tmp_path):
    """Atomic hot-reload core promise: a reload that fails validation must leave
    the current entry intact and versioned as before."""
    src = tmp_path / "r.json"
    src.write_text(_full_spec(), encoding="utf-8")
    reg = RegimeRegistry()
    entry1 = reg.load(src)
    # mutate the source file to an invalid regime (empty flow nodes)
    src.write_text(json.dumps(
        {"name": "my-regime", "flow": {"entry": "x", "nodes": []}},
        ensure_ascii=False), encoding="utf-8")
    with pytest.raises(FlowError):
        reg.reload("my-regime")
    cur = reg.get("my-regime")
    assert cur is not None
    assert cur.version == entry1.version


def test_regime_store_residual_verify_whitelist_rejected_at_load(tmp_path):
    """A regime-store entry whose flow's verify command is outside the
    docker-exec whitelist (e.g. a stale `sg docker -c` wrapper — the 2026-08-14
    nightly residue) is isolated at STORE-LOAD time: the StateMachine
    construction point rejects it, so it can never reach a run."""
    store = tmp_path / "store"
    store.mkdir()
    spec = json.loads(_full_spec())
    nodes = spec["flow"]["nodes"]
    # make the judge node carry a non-whitelisted verify command
    for n in nodes:
        if n.get("type") == "judge":
            n["verify"] = "sg docker -c \"docker exec {container} bash -c 'pytest -q'\""
    (store / "my-regime.json").write_text(
        json.dumps({"name": "my-regime", "spec": spec}), encoding="utf-8")
    reg = RegimeRegistry(store_dir=store)
    assert reg.regime("my-regime") is None, \
        "residual non-whitelisted verify must be rejected at regime store load"


def test_regime_registry_load_with_name_override_roundtrips(tmp_path):
    """W6: loading a regime file under an explicit override name must keep the
    serialized flow keyed consistently (to_dict -> from_dict stays valid)."""
    src = tmp_path / "r.json"
    src.write_text(_full_spec(), encoding="utf-8")
    reg = RegimeRegistry(store_dir=tmp_path / "store")
    entry = reg.load(src, name="renamed")
    assert entry.regime.name == "renamed"
    # round-trip through a fresh registry (persistence) must not break
    reg2 = RegimeRegistry(store_dir=tmp_path / "store")
    r2 = reg2.regime("renamed")
    assert r2 is not None
    assert list(r2.flow.flow_path()) == list(entry.regime.flow.flow_path())


def test_regime_registry_load_name_override_rejects_path_escape(tmp_path):
    """W2: an explicit --name override must pass the safe-name charset (no
    store-path traversal via a '../' name)."""
    src = tmp_path / "r.json"
    src.write_text(_full_spec(), encoding="utf-8")
    reg = RegimeRegistry(store_dir=tmp_path / "store")
    with pytest.raises(FlowError):
        reg.load(src, name="../evil")
    assert not (tmp_path / "evil.json").exists()


def test_regime_registry_remove(tmp_path):
    reg = RegimeRegistry(store_dir=tmp_path / "store")
    reg.register(compile_regime(_full_spec()), validate=True)
    assert reg.remove("my-regime") is True
    assert reg.remove("my-regime") is False
    assert not (tmp_path / "store" / "my-regime.json").exists()


def test_regime_registry_load_file(tmp_path):
    p = tmp_path / "r.json"
    p.write_text(_full_spec(), encoding="utf-8")
    reg = RegimeRegistry()
    entry = reg.load(p)
    assert entry.regime.name == "my-regime"
    assert reg.regime("my-regime").watchdog is not None


# -- driver integration -------------------------------------------------------


def _driver(regime, **settings_overrides):
    opts = dict(monitor_enabled=False, poll_sec=0.1)
    opts.update(settings_overrides)
    s = Settings(**opts)
    return StatechartDriver.from_regime(
        regime, s, MockClient(sm=regime.flow), enforce_invariants=True)


def test_from_regime_drives_flow_to_complete():
    regime = compile_regime(_full_spec())
    d = _driver(regime)
    outcome, end, _ = d.run("任务")
    assert outcome == Outcome.COMPLETE
    assert end == "b"


def test_regime_stall_sec_overrides_settings():
    """The regime's supervision threshold wins over the settings default."""
    regime = compile_regime(_full_spec(stall_sec=2))
    d = _driver(regime, stall_sec=999)
    assert d.watchdog.stall_sec == 2


def test_regime_watchdog_policy_wired():
    regime = compile_regime(_full_spec(watchdog={"soft_sec": 30, "hard_sec": 600}))
    d = _driver(regime)
    assert d.watchdog.policy.name == "operator"
    assert len(d.watchdog.policy.rules) == 2


def test_regime_handover_policy_wired():
    regime = compile_regime(_full_spec(handover={"soft_fraction": 0.4, "hard_fraction": 0.8}))
    d = _driver(regime)
    assert d.workflow._context_policy is not None
    assert d.workflow._context_policy.soft_fraction == 0.4


def test_regime_no_override_falls_back_to_settings():
    regime = compile_regime(_full_spec(stall_sec=None))
    d = _driver(regime, stall_sec=123)
    assert d.watchdog.stall_sec == 123


def test_regime_auto_resume_override():
    regime = compile_regime(_full_spec(auto_resume_sec=7))
    d = _driver(regime, auto_resume_sec=999)
    assert d.watchdog.auto_resume_sec == 7


def test_regime_handover_none_falls_back_to_settings_json():
    """No regime handover declaration -> the settings JSON policy drives it."""
    import json as _json
    settings_policy = _json.dumps({"soft_fraction": 0.6, "hard_fraction": 0.9})
    regime = compile_regime(_full_spec(handover=None))
    s = Settings(monitor_enabled=False, poll_sec=0.1,
                 context_handover_policy_json=settings_policy)
    d = StatechartDriver.from_regime(
        regime, s, MockClient(sm=regime.flow), enforce_invariants=True)
    assert d.workflow._context_policy is not None
    assert d.workflow._context_policy.soft_fraction == 0.6
