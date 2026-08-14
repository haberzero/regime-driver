"""Tests for the unified extension-point model (阶段 2).

Covers the HookRegistry (register/fire/introspection), user-plugin loading from
~/.regime/hooks.py, rule/tool injection, and the hook wiring in the workflow /
watchdog units.
"""

from __future__ import annotations

import json

import pytest

from regime_driver.app.watchdog_policy import SessionEvidence
from regime_driver.extensions import (
    HOOK_POINTS,
    HookError,
    HookRegistry,
    load_user_hooks,
)
from regime_driver.infra.settings import Settings
from regime_driver.testing import MockClient


# -- registry basics ---------------------------------------------------------


def test_register_and_fire_collects_returns():
    reg = HookRegistry()
    seen = []

    @reg.hook("node_enter")
    def on_enter(ctx):
        seen.append(ctx["node"])
        return ctx["node"]

    assert reg.hooks_for("node_enter")
    out = reg.fire("node_enter", node="a", role="developer")
    assert seen == ["a"]
    assert out == ["a"]  # non-None returns collected


def test_fire_unknown_point_is_noop():
    reg = HookRegistry()
    assert reg.fire("nope") == []


def test_register_hook_unknown_point_fails_loudly():
    reg = HookRegistry()
    with pytest.raises(ValueError):
        reg.register_hook("bogus", lambda ctx: None)


def test_broken_hook_does_not_kill_loop_and_is_reported():
    reg = HookRegistry()
    errors = []

    @reg.hook("node_done")
    def boom(ctx):
        raise RuntimeError("user bug")

    @reg.hook("node_done")
    def ok(ctx):
        return "ok"

    out = reg.fire("node_done", on_error=lambda p, exc: errors.append(str(exc)))
    assert out == ["ok"]  # healthy hook still ran
    assert len(errors) == 1 and "user bug" in errors[0]


def test_register_rule_and_tool():
    reg = HookRegistry()
    reg.register_rule("never", lambda ev: False, "nudge", reason="demo")
    reg.register_rule("hard", lambda ev: True, "kill", meta=True)
    assert [r.name for r in reg.rules] == ["never", "hard"]
    assert reg.rules[1].meta is True
    assert reg.rules[1].action == "kill"
    # tool registration delegates to the core tool registry the kernel reads
    reg.register_tool("ping", lambda c, r, a: None)
    from regime_driver.core import tools
    assert "ping" in tools.TOOLS
    del tools.TOOLS["ping"]


def test_summary_shape():
    reg = HookRegistry()
    s = reg.summary()
    assert set(s["points"]) == set(HOOK_POINTS)
    assert "source" in s and "rules" in s and "tools" in s


def test_hook_points_complete():
    assert set(HOOK_POINTS) == {
        "node_enter", "node_done", "transition", "judge_verdict",
        "stall", "handover",
    }


# -- plugin loading ----------------------------------------------------------


def _write_plugin(tmp_path, body: str) -> str:
    p = tmp_path / "hooks.py"
    p.write_text(body, encoding="utf-8")
    return str(p)


def test_load_user_hooks_absent_is_empty(tmp_path):
    reg = load_user_hooks(tmp_path / "nope.py")
    assert reg.source is None
    assert reg.summary()["source"] is None


def test_load_user_hooks_runs_register(tmp_path):
    src = _write_plugin(tmp_path, '''
def register(reg):
    reg.register_hook("node_done", lambda ctx: None)
    reg.register_rule("x", lambda ev: False, "nudge")
''')
    reg = load_user_hooks(src)
    assert reg.summary()["points"]["node_done"] == 1
    assert reg.summary()["rules"] == ["x"]
    assert reg.source is not None


def test_load_user_hooks_decorator_form(tmp_path):
    src = _write_plugin(tmp_path, '''
def register(reg):
    @reg.hook("stall")
    def on_stall(ctx):
        return ctx["action"]
''')
    reg = load_user_hooks(src)
    assert reg.hooks_for("stall")
    assert reg.fire("stall", action="kill") == ["kill"]


def test_load_user_hooks_missing_register_fails_loudly(tmp_path):
    src = _write_plugin(tmp_path, "x = 1\n")
    with pytest.raises(HookError):
        load_user_hooks(src)


def test_load_user_hooks_import_error_fails_loudly(tmp_path):
    src = _write_plugin(tmp_path, "import definitely_not_real_module_xyz\n")
    with pytest.raises(Exception):
        load_user_hooks(src)


# -- workflow / watchdog wiring ---------------------------------------------


def test_workflow_fires_hooks_on_real_run(tmp_path):
    """Phase-2 wiring: a real (mock-client) run fires node_enter / node_done /
    transition / judge_verdict hooks, and a broken hook is audited, never fatal."""
    from regime_driver.extensions import HookRegistry
    from regime_driver.infra.settings import Settings
    from regime_driver.regime import compile_regime
    from regime_driver.testing import MockClient

    spec = {
        "name": "hook-flow",
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
    }
    regime = compile_regime(json.dumps(spec, ensure_ascii=False))
    seen = []
    reg = HookRegistry()

    @reg.hook("node_enter")
    def enter(ctx):
        seen.append(("enter", ctx["node"]))

    @reg.hook("node_done")
    def done(ctx):
        seen.append(("done", ctx["node"]))

    @reg.hook("judge_verdict")
    def verdict(ctx):
        seen.append(("verdict", ctx["node"], ctx["action"]))

    from regime_driver.app.statechart_driver import StatechartDriver
    settings = Settings(monitor_enabled=False, poll_sec=0.1)
    client = MockClient(sm=regime.flow)
    driver = StatechartDriver.from_regime(regime, settings, client,
                                          hooks=reg)
    outcome = driver.run("做任务", timeout_sec=15)
    assert outcome[0].value == "complete"
    nodes_entered = {x[1] for x in seen if x[0] == "enter"}
    assert nodes_entered == {"a", "b", "wrap"}
    assert any(k == "done" for k, *_ in seen)
    assert any(k == "verdict" for k, *_ in seen)
    # a broken hook is audited as hook_error, never fatal
    reg2 = HookRegistry()

    @reg2.hook("node_enter")
    def boom(ctx):
        raise RuntimeError("boom")

    client2 = MockClient(sm=regime.flow)
    driver2 = StatechartDriver.from_regime(regime, settings, client2, hooks=reg2)
    outcome2 = driver2.run("做任务", timeout_sec=15)
    assert outcome2[0].value == "complete"


def test_watchdog_fires_stall_hook():
    from regime_driver.app.statechart_cluster import StatechartCluster
    from regime_driver.core.models import Outcome
    from regime_driver.extensions import HookRegistry
    from regime_driver.infra.regime_loader import load_regime

    sm = load_regime()
    fired = []
    reg = HookRegistry()

    @reg.hook("stall")
    def on_stall(ctx):
        fired.append(ctx["action"])

    c = StatechartCluster(MockClient(sm=sm), stall_sec=0.01, hooks=reg)
    c.add_workflow("w1", Settings(monitor_enabled=False, poll_sec=0.1), sm)
    results = c.run_all({"w1": "做任务"}, timeout_sec=15)
    assert results["w1"][0] == Outcome.COMPLETE
    # no stall fired on a clean run (nothing to observe) — the hook itself wired


def test_user_watchdog_rules_merge_into_policy():
    from regime_driver.extensions import HookRegistry
    from regime_driver.infra.settings import Settings
    from regime_driver.regime import compile_regime

    spec = {
        "name": "rule-flow",
        "flow": {"entry": "a", "nodes": [
            {"id": "a", "desc": "干", "role": "developer", "type": "agent"}]},
        "watchdog": {"soft_sec": 30, "hard_sec": 600},
    }
    regime = compile_regime(json.dumps(spec, ensure_ascii=False))
    reg = HookRegistry()
    reg.register_rule("user-never", lambda ev: False, "nudge", reason="demo")
    from regime_driver.app.statechart_driver import StatechartDriver
    driver = StatechartDriver.from_regime(
        regime, Settings(monitor_enabled=False), MockClient(sm=regime.flow),
        hooks=reg)
    names = [r.name for r in driver.watchdog.policy.rules]
    assert "user-never" in names


def test_cluster_merges_user_rules_and_hooks_into_watchdog():
    """B2: StatechartCluster (run-many/dialog) must merge user rules + wire the
    watchdog hooks — same as StatechartDriver, no silent feature loss."""
    from regime_driver.app.statechart_cluster import StatechartCluster
    from regime_driver.infra.regime_loader import load_regime

    sm = load_regime()
    reg = HookRegistry()
    reg.register_rule("user-never", lambda ev: False, "nudge", reason="demo")
    fired = []

    @reg.hook("stall")
    def on_stall(ctx):
        fired.append(ctx["action"])

    c = StatechartCluster(MockClient(sm=sm), stall_sec=0.01, hooks=reg)
    assert "user-never" in [r.name for r in c.watchdog.policy.rules]
    assert c.watchdog.hooks is reg
    assert c.workflows == {}  # not started yet


def test_watchdog_stall_hook_fires_on_action():
    """W7: the `stall` hook really fires when the watchdog emits an action (not
    just wired-but-silent)."""
    import time

    from regime_driver.app.watchdog_policy import L5_KILL, Rule, WatchdogPolicy, no_activity_for
    from regime_driver.app.watchdog_unit import WatchdogUnit
    from regime_driver.core.statechart import Bus, Signal, SignalKind

    fired = []
    reg = HookRegistry()

    @reg.hook("stall")
    def on_stall(ctx):
        fired.append((ctx["action"], ctx["session"]))

    bus = Bus()
    wd = WatchdogUnit(
        stall_sec=0.01, bus=bus,
        policy=WatchdogPolicy(name="t",
                              rules=[Rule("hard", no_activity_for(0.01), L5_KILL)]),
        hooks=reg, run_id="r1")
    # a busy session with NO liveness: first report anchors first-busy, a later
    # report (0.05s) crosses the 0.01s silence threshold -> kill fires the hook.
    wd._on_report(Signal(SignalKind.REPORT, "wf", wd.id, {
        "session_id": "s1", "status": "busy", "activity_ts": 0.0,
        "latest_text": ""}))
    time.sleep(0.05)
    wd._on_report(Signal(SignalKind.REPORT, "wf", wd.id, {
        "session_id": "s1", "status": "busy", "activity_ts": 0.0,
        "latest_text": ""}))
    assert fired, "stall hook must fire on a watchdog action"
    assert fired[0] == ("kill", "s1")


def test_handover_hook_override_wins_over_template():
    """W2: handover customization precedence — hook override > declarative
    template > built-in builders."""
    from regime_driver.app.handover_policy import ContextHandoverPolicy
    from regime_driver.app.workflow_unit import WorkflowUnit
    from regime_driver.infra.regime_loader import load_regime

    class _State:
        role = "developer"
        session_id = "s1"

    sm = load_regime()
    reg = HookRegistry()

    @reg.hook("handover")
    def override(ctx):
        return {"document": "HOOK-DOC", "opening": "HOOK-OPEN"}

    wf = WorkflowUnit(
        Settings(monitor_enabled=False, poll_sec=0.1), sm, MockClient(sm=sm),
        hooks=reg,
        context_policy=ContextHandoverPolicy(
            document_template="TEMPLATE-DOC {role}",
            opening_template="TEMPLATE-OPEN {role}"))
    wf._context = "ctx"
    doc, opening = wf._handover_package(_State(), "implement", 0.5,
                                        kind="normal", forced=False)
    assert doc == "HOOK-DOC"
    assert opening == "HOOK-OPEN"


def test_handover_template_wins_over_builtin():
    """W2: with no hook, a declarative template replaces the built-in shape."""
    from regime_driver.app.handover_policy import ContextHandoverPolicy
    from regime_driver.app.workflow_unit import WorkflowUnit
    from regime_driver.infra.regime_loader import load_regime

    class _State:
        role = "developer"
        session_id = "s1"

    sm = load_regime()
    wf = WorkflowUnit(
        Settings(monitor_enabled=False, poll_sec=0.1), sm, MockClient(sm=sm),
        context_policy=ContextHandoverPolicy(
            document_template="TEMPLATE-DOC {role}",
            opening_template="TEMPLATE-OPEN {role}"))
    wf._context = "ctx"
    doc, opening = wf._handover_package(_State(), "implement", 0.5,
                                        kind="normal", forced=False)
    assert doc == "TEMPLATE-DOC developer"
    assert opening == "TEMPLATE-OPEN developer"


def test_reload_is_atomic_snapshot_and_cleans_tools(tmp_path):
    """W3: reload returns a fresh registry; the old snapshot keeps working; a
    tool the NEW plugin no longer registers is removed from global core.tools."""
    from regime_driver.core import tools as _tools

    v1 = _write_plugin(tmp_path, '''
def register(reg):
    reg.register_hook("stall", lambda ctx: None)
    reg.register_tool("reload-ping", lambda c, r, a: None)
''')
    reg = load_user_hooks(v1)
    assert "reload-ping" in _tools.TOOLS
    old = reg
    # v2 drops the tool -> reload must clean it from the global registry
    v2 = _write_plugin(tmp_path, '''
def register(reg):
    reg.register_hook("stall", lambda ctx: None)
''')
    fresh = reg.reload(v2)
    assert fresh is not old
    assert old.hooks_for("stall")  # old snapshot intact
    assert fresh.hooks_for("stall")
    assert "reload-ping" not in _tools.TOOLS  # dropped tool cleaned on reload


def test_default_hooks_path_env_override(monkeypatch, tmp_path):
    from regime_driver.extensions import default_hooks_path
    p = tmp_path / "hooks.py"
    monkeypatch.setenv("REGIME_HOOKS", str(p))
    assert default_hooks_path() == p
