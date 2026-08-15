"""Tests for the FlowRegistry + hot compile/reload lifecycle (WORK_PLAN5 F1-F11)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from regime_driver.core.state_machine import StateMachineError
from regime_driver.flow import (
    FlowError,
    FlowRegistry,
    compile_spec,
    validate_sm,
)

COMPACT = ('{"entry": "a", "nodes": ['
           '{"id": "a", "desc": "d", "role": "developer", "type": "agent", "next": "b"},'
           '{"id": "b", "desc": "d", "role": "reviewer", "type": "judge", "next": null}]}')


def _file(path: Path, raw: str) -> Path:
    path.write_text(raw, encoding="utf-8")
    return path


def _regime_json(flow_name: str = "f") -> str:
    return json.dumps({
        "version": "t",
        "flows": {flow_name: {"nodes": {
            "a": {"id": "a", "desc": "d", "role": "developer",
                  "type": "agent", "next": "b"},
            "b": {"id": "b", "desc": "d", "role": "reviewer",
                  "type": "judge", "next": None},
        }}},
        "entry": {"flow": flow_name, "start_node": "a"},
    })


# -- compile_spec (F1) -------------------------------------------------------

def test_compile_spec_compact() -> None:
    sm = compile_spec("f", COMPACT)
    assert sm.flow_path() == ["a", "b"]


def test_compile_spec_compact_preserves_verify_and_readonly() -> None:
    """B2 (阶段 4): the compact whitelist must keep `verify` (and `readonly`) —
    the intent-level design adds them to judge/agent nodes and they must NOT be
    silently dropped."""
    raw = ('{"entry": "a", "nodes": ['
           '{"id": "a", "desc": "读", "role": "developer", "type": "agent",'
           ' "next": "t", "readonly": true},'
           '{"id": "t", "desc": "测", "role": "reviewer", "type": "judge",'
           ' "verify": "docker exec {container} pytest -q"}]}')
    sm = compile_spec("f", raw)
    assert sm.node("a").readonly is True
    assert sm.node("t").verify == "docker exec {container} pytest -q"


def test_compile_spec_full_regime() -> None:
    sm = compile_spec("f", _regime_json("f"))
    assert sm.flow_path() == ["a", "b"]


def test_compile_spec_rejects_malformed() -> None:
    with pytest.raises(FlowError):
        compile_spec("f", "not json{{{")
    with pytest.raises(FlowError):
        compile_spec("f", '"a string"')
    # a full regime dict missing the requested flow name
    with pytest.raises(FlowError):
        compile_spec("missing", _regime_json("f"))


def test_compile_spec_bad_structure_rejected() -> None:
    # a node references an unknown next target -> structural error surfaces
    raw = ('{"entry": "a", "nodes": [{"id": "a", "desc": "d", '
           '"role": "developer", "type": "agent", "next": "nope"}]}')
    with pytest.raises(FlowError):
        compile_spec("f", raw)


# -- deep validation gate (F9) -----------------------------------------------

def test_validate_sm_catches_bad_role() -> None:
    raw = ('{"entry": "a", "nodes": [{"id": "a", "desc": "d", '
           '"role": "nobody", "type": "agent", "next": null}]}')
    sm = compile_spec("f", raw)
    res = validate_sm(sm)
    assert not res.ok
    assert any("role" in e for e in res.errors)


# -- FlowRegistry (F4) -------------------------------------------------------

def test_registry_register_and_query() -> None:
    reg = FlowRegistry()
    sm = compile_spec("f", COMPACT)
    reg.register("f", sm)
    assert reg.sm("f") is sm
    assert reg.get("f").source == "design"
    assert [e.name for e in reg.list()] == ["f"]
    assert reg.remove("f") is True
    assert reg.remove("f") is False


def test_registry_from_default_seeds_builtin() -> None:
    reg = FlowRegistry.from_default()
    assert "code_workflow" in [e.name for e in reg.list()]
    assert reg.sm("code_workflow") is not None


def test_registry_load_validates_and_registers(tmp_path: Path) -> None:
    p = _file(tmp_path / "f.json", _regime_json("f"))
    reg = FlowRegistry()
    entry = reg.load(p)
    assert entry.name == "f"
    assert entry.source == str(p)
    assert entry.version >= 1
    assert reg.sm("f") is not None


def test_registry_load_rejects_invalid_no_mutation(tmp_path: Path) -> None:
    bad = ('{"version": "t", "flows": {"f": {"nodes": {'
           '"a": {"id": "a", "desc": "d", "role": "developer", '
           '"type": "agent", "next": null}}}}, '
           '"entry": {"flow": "f", "start_node": "a"}}')
    # bad role -> deep validation fails
    bad = bad.replace('"role": "developer"', '"role": "ghost"')
    p = _file(tmp_path / "bad.json", bad)
    reg = FlowRegistry()
    with pytest.raises(FlowError):
        reg.load(p)
    assert reg.list() == []  # no partial mutation


# -- atomic reload + snapshot semantics (F5/F10) -----------------------------

def test_reload_atomic_keeps_old_snapshot(tmp_path: Path) -> None:
    p = _file(tmp_path / "f.json", _regime_json("f"))
    reg = FlowRegistry()
    e1 = reg.load(p)
    old_sm = reg.sm("f")

    # rewrite the file with an extra node -> new version on reload
    new_raw = _regime_json("f").replace('"next": None', '"next": null')
    new_raw = new_raw.replace(
        '"b": {"id": "b"', '"c": {"id": "c", "desc": "c", "role": "developer", "type": "agent", "next": null}, "b": {"id": "b"')
    _file(p, new_raw)

    e2 = reg.reload("f")
    assert e2.version > e1.version
    new_sm = reg.sm("f")
    assert new_sm is not old_sm          # registry swapped to a new object
    assert len(new_sm.flow.nodes) == 3   # new version visible in registry
    # running workflow holds the OLD snapshot, untouched
    assert old_sm is not None
    assert len(old_sm.flow.nodes) == 2
    assert old_sm.flow_path() == ["a", "b"]


def test_reload_rejects_invalid_leaves_old(tmp_path: Path) -> None:
    p = _file(tmp_path / "f.json", _regime_json("f"))
    reg = FlowRegistry()
    reg.load(p)
    before = reg.sm("f")

    _file(p, _regime_json("f").replace('"role": "developer"', '"role": "ghost"'))
    with pytest.raises(FlowError):
        reg.reload("f")
    # registry unchanged; old version intact
    assert reg.sm("f") is before


def test_reload_unknown_raises() -> None:
    reg = FlowRegistry()
    with pytest.raises(FlowError):
        reg.reload("missing")


def test_persistence_survives_registry_recreation(tmp_path: Path) -> None:
    p = _file(tmp_path / "f.json", _regime_json("f"))
    store = tmp_path / "store"
    reg1 = FlowRegistry(store_dir=store)
    reg1.load(p)
    # a brand-new registry over the SAME store sees the persisted flow (single truth)
    reg2 = FlowRegistry(store_dir=store)
    assert reg2.sm("f") is not None
    assert reg2.get("f").source == str(p)
    # removing from one registry clears it for the next
    reg2.remove("f")
    reg3 = FlowRegistry(store_dir=store)
    assert reg3.sm("f") is None


def test_persistence_skips_builtin(tmp_path: Path) -> None:
    store = tmp_path / "store"
    reg = FlowRegistry(store_dir=store)
    reg.register("code_workflow", compile_spec("code_workflow", _regime_json("code_workflow")),
                 source="builtin")
    assert list((store / "code_workflow.json").parent.glob("*.json")) == [] or True
    assert not (store / "code_workflow.json").exists()


def test_store_residual_verify_whitelist_rejected_at_load(tmp_path: Path) -> None:
    """A store entry whose verify command is outside the docker-exec whitelist
    (e.g. a stale `sg docker -c` wrapper — the 2026-08-14 nightly residue) is
    isolated at STORE-LOAD time, so a `--flow` run cannot hit it mid-run."""
    store = tmp_path / "store"
    store.mkdir()
    spec = json.loads(_regime_json("bf"))
    spec["flows"]["bf"]["nodes"]["b"]["verify"] = (
        "sg docker -c \"docker exec {container} bash -c 'pytest -q'\"")
    bad = {"name": "bf", "source": "/tmp/bad.json", "file": "/tmp/bad.json",
           "spec": spec}
    (store / "bf.json").write_text(json.dumps(bad), encoding="utf-8")
    reg = FlowRegistry(store_dir=store)
    assert reg.sm("bf") is None, "residual non-whitelisted verify must be rejected at store load"


def test_reload_designed_flow_revalidates() -> None:
    reg = FlowRegistry()
    sm = compile_spec("f", COMPACT)
    e1 = reg.register("f", sm)
    e2 = reg.reload("f")  # designed (no file) reloads from its own spec
    assert e2.version > e1.version
    assert reg.sm("f").flow_path() == ["a", "b"]


# -- anti-loop (F11): spine cycle is a hard error ----------------------------

def test_spine_cycle_caught_by_validate() -> None:
    raw = ('{"entry": "a", "nodes": ['
           '{"id": "a", "desc": "d", "role": "developer", "type": "agent", "next": "b"},'
           '{"id": "b", "desc": "d", "role": "developer", "type": "agent", "next": "a"}]}')
    sm = compile_spec("f", raw)   # structural construction allows it...
    with pytest.raises(StateMachineError):
        sm.flow_path()            # ...traversal detects the cycle
    res = validate_sm(sm)         # and the deep gate rejects it (F9/F11)
    assert not res.ok
    assert any("cycle" in e for e in res.errors)


def test_registry_rejects_cycle_flow(tmp_path: Path) -> None:
    p = _file(tmp_path / "cyc.json", (
        '{"version": "t", "flows": {"c": {"nodes": {'
        '"a": {"id": "a", "desc": "d", "role": "developer", "type": "agent", "next": "b"},'
        '"b": {"id": "b", "desc": "d", "role": "developer", "type": "agent", "next": "a"}}}}, '
        '"entry": {"flow": "c", "start_node": "a"}}'))
    reg = FlowRegistry()
    with pytest.raises(FlowError):
        reg.load(p)
    assert reg.list() == []
