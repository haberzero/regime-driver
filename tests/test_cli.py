"""CLI command-level tests (G14): exercise real commands, not just helpers.

Covers commands that need no live worker: validate --json/--deep, preflight
(offline MockClient), report (empty), and the mandatory permission gate.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from regime_driver.cli import app, _reset_flow_registry, _reset_regime_registry

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate_flow_registry(tmp_path, monkeypatch):
    # isolate the persistent flow store: fresh in-process registry + a temp
    # store dir, so CLI flow load/rm never touch the user's real ~/.regime/flows
    # and never leak across tests.
    monkeypatch.setenv("REGIME_FLOW_STORE", str(tmp_path / "flowstore"))
    monkeypatch.setenv("REGIME_STORE", str(tmp_path / "regimestore"))
    _reset_flow_registry()
    _reset_regime_registry()
    yield
    _reset_flow_registry()
    _reset_regime_registry()


def test_validate_json_ok():
    res = runner.invoke(app, ["validate", "--json"])
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert data["ok"] is True
    assert data["flow"] == "code_workflow"


def test_validate_deep_default_on():
    # --deep is ON by default; with the fixed default skills path it should pass
    res = runner.invoke(app, ["validate", "--json"])
    data = json.loads(res.output)
    assert data.get("deep", {}).get("ok") is True


def test_preflight_offline_completes():
    res = runner.invoke(app, ["preflight", "--json"])
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert data["ok"] is True
    assert data["outcome"] == "complete"


def test_preflight_stall_fails():
    res = runner.invoke(app, ["preflight", "--fault", "stall", "--stall-sec", "1",
                              "--json"])
    assert res.exit_code == 1
    data = json.loads(res.output)
    assert data["ok"] is False


def test_run_preflight_honesty_note_helper_exists():
    """Regression (B1): the passing-preflight path of `regime run` calls
    `_note(...)` which must exist (a missing symbol would crash every default
    `regime run` right after 'preflight PASSED')."""
    from regime_driver.cli.__init__ import _note
    assert callable(_note)


def test_report_empty():
    res = runner.invoke(app, ["report", "--json"])
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert data["rollups"] == []


def test_permission_ceiling_blocks_self_elevation(monkeypatch):
    monkeypatch.setenv("REGIME_PERMISSION_CEILING", "read")
    res = runner.invoke(app, ["run", "x", "--perm", "clean", "--no-preflight"])
    assert res.exit_code == 1
    assert "permission denied" in res.output


def test_drive_permission_gate_blocks_low_perm(monkeypatch):
    # drive is a write op; a low held permission must be rejected before any worker
    monkeypatch.setenv("REGIME_PERMISSION_CEILING", "read")
    res = runner.invoke(app, ["drive", "x", "--perm", "clean", "--no-preflight"])
    assert res.exit_code == 1
    assert "permission denied" in res.output


def test_scaffold_permission_gate_blocks_low_perm(monkeypatch, tmp_path):
    # scaffold writes templates into a config root -> RUN; a READ-holder must be rejected
    monkeypatch.setenv("REGIME_PERMISSION_CEILING", "read")
    res = runner.invoke(app, ["scaffold", "--target", str(tmp_path), "--dry-run"])
    assert res.exit_code == 1
    assert "permission denied" in res.output
    assert not (tmp_path / "agents").exists()


def test_setup_guided_assembly(tmp_path):
    """regime setup: guided first-time install. Deploys templates to --target and
    reports env detection + a host-mode-ready flag (deployment UX)."""
    res = runner.invoke(app, ["setup", "--target", str(tmp_path), "--json"])
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert data["templates_copied"] >= 1
    assert (tmp_path / "agents" / "dialog-control.md").is_file()
    assert (tmp_path / "plugins" / "regime-dialog-control.js").is_file()
    assert (tmp_path / "opencode.json").is_file()
    # env detection reported
    assert "docker_available" in data
    assert "opencode_available" in data
    assert "key_present" in data
    assert data["target"] == str(tmp_path)


def test_setup_permission_gate(monkeypatch, tmp_path):
    monkeypatch.setenv("REGIME_PERMISSION_CEILING", "read")
    res = runner.invoke(app, ["setup", "--target", str(tmp_path), "--json"])
    assert res.exit_code == 1
    assert "permission denied" in res.output


def test_flow_list_json():
    res = runner.invoke(app, ["flow", "list", "--json"])
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert data["flows"][0]["name"] == "code_workflow"
def test_flow_inspect_json():
    res = runner.invoke(app, ["flow", "inspect", "code_workflow", "--json"])
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert data["name"] == "code_workflow"
    assert data["nodes"] == 6


def test_flow_validate_file_ok(tmp_path):
    reg = tmp_path / "f.json"
    reg.write_text(
        '{"version": "t", "flows": {"f": {"nodes": {'
        '"a": {"id": "a", "desc": "d", "role": "developer", "type": "agent", "next": null}}}}, '
        '"entry": {"flow": "f", "start_node": "a"}}', encoding="utf-8")
    res = runner.invoke(app, ["flow", "validate", str(reg), "--json"])
    assert res.exit_code == 0
    assert json.loads(res.output)["ok"] is True


def test_flow_validate_file_rejects_bad_role(tmp_path):
    reg = tmp_path / "bad.json"
    reg.write_text(
        '{"version": "t", "flows": {"f": {"nodes": {'
        '"a": {"id": "a", "desc": "d", "role": "ghost", "type": "agent", "next": null}}}}, '
        '"entry": {"flow": "f", "start_node": "a"}}', encoding="utf-8")
    res = runner.invoke(app, ["flow", "validate", str(reg), "--json"])
    assert res.exit_code == 1
    assert json.loads(res.output)["ok"] is False


def test_flow_load_is_write_gated(monkeypatch, tmp_path):
    reg = tmp_path / "f.json"
    reg.write_text(
        '{"version": "t", "flows": {"f": {"nodes": {'
        '"a": {"id": "a", "desc": "d", "role": "developer", "type": "agent", "next": null}}}}, '
        '"entry": {"flow": "f", "start_node": "a"}}', encoding="utf-8")
    monkeypatch.setenv("REGIME_PERMISSION_CEILING", "read")
    res = runner.invoke(app, ["flow", "load", str(reg), "--perm", "run"])
    assert res.exit_code == 1
    assert "permission denied" in res.output


def test_flow_reload_is_write_gated(monkeypatch):
    monkeypatch.setenv("REGIME_PERMISSION_CEILING", "read")
    res = runner.invoke(app, ["flow", "reload", "code_workflow", "--perm", "run"])
    assert res.exit_code == 1
    assert "permission denied" in res.output


def test_flow_load_then_list(tmp_path):
    reg = tmp_path / "f.json"
    reg.write_text(
        '{"version": "t", "flows": {"f": {"nodes": {'
        '"a": {"id": "a", "desc": "d", "role": "developer", "type": "agent", "next": null}}}}, '
        '"entry": {"flow": "f", "start_node": "a"}}', encoding="utf-8")
    r1 = runner.invoke(app, ["flow", "load", str(reg), "--json"])
    assert r1.exit_code == 0
    assert json.loads(r1.output)["ok"] is True
    r2 = runner.invoke(app, ["flow", "list", "--json"])
    names = [e["name"] for e in json.loads(r2.output)["flows"]]
    assert "f" in names


def test_flow_load_rejects_invalid_keeps_registry_clean(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text(
        '{"version": "t", "flows": {"f": {"nodes": {'
        '"a": {"id": "a", "desc": "d", "role": "ghost", "type": "agent", "next": null}}}}, '
        '"entry": {"flow": "f", "start_node": "a"}}', encoding="utf-8")
    r1 = runner.invoke(app, ["flow", "load", str(bad), "--json"])
    assert r1.exit_code == 1
    assert json.loads(r1.output)["ok"] is False
    r2 = runner.invoke(app, ["flow", "list", "--json"])
    names = [e["name"] for e in json.loads(r2.output)["flows"]]
    assert "f" not in names  # no partial mutation


def test_flow_design_inline_registers(tmp_path):
    """flow design takes an inline spec (no file) and persists it (P0 dialog-control design)."""
    compact = ('{"entry":"start","nodes":['
               '{"id":"start","desc":"理解","role":"developer","type":"agent","next":"judge"},'
               '{"id":"judge","desc":"判定","role":"reviewer","type":"judge","next":null}]}')
    r1 = runner.invoke(app, ["flow", "design", "mini", compact, "--json"])
    assert r1.exit_code == 0, r1.output
    data = json.loads(r1.output)
    assert data["ok"] is True and data["name"] == "mini"
    assert data["nodes"] == 2 and data["path"] == ["start", "judge"]
    # persists: a fresh registry (same store) sees it
    r2 = runner.invoke(app, ["flow", "list", "--json"])
    names = [e["name"] for e in json.loads(r2.output)["flows"]]
    assert "mini" in names


def test_flow_design_rejects_invalid_no_mutation(tmp_path):
    bad = ('{"entry":"start","nodes":['
           '{"id":"start","desc":"x","role":"ghost","type":"agent","next":null}]}')
    r1 = runner.invoke(app, ["flow", "design", "mini-bad", bad, "--json"])
    assert r1.exit_code == 1
    assert json.loads(r1.output)["ok"] is False
    r2 = runner.invoke(app, ["flow", "list", "--json"])
    names = [e["name"] for e in json.loads(r2.output)["flows"]]
    assert "mini-bad" not in names  # no partial mutation


def test_flow_design_preflight_failure_no_mutation(tmp_path):
    """A failed preflight must not leave the flow registered/persisted."""
    spec = ('{"entry":"a","nodes":['
            '{"id":"a","desc":"x","role":"developer","type":"agent","next":null}]}')
    r1 = runner.invoke(app, ["flow", "design", "p-bad", spec,
                             "--preflight", "--preflight-fault", "stall",
                             "--preflight-stall-sec", "1", "--json"])
    assert r1.exit_code == 1
    assert json.loads(r1.output)["ok"] is False
    r2 = runner.invoke(app, ["flow", "list", "--json"])
    names = [e["name"] for e in json.loads(r2.output)["flows"]]
    assert "p-bad" not in names


def test_flow_design_is_write_gated(monkeypatch):
    monkeypatch.setenv("REGIME_PERMISSION_CEILING", "read")
    res = runner.invoke(app, ["flow", "design", "x",
                              '{"entry":"a","nodes":[{"id":"a","desc":"d",'
                              '"role":"developer","type":"agent","next":null}]}',
                              "--perm", "run"])
    assert res.exit_code == 1
    assert "permission denied" in res.output


def test_status_deep_aggregates(monkeypatch, tmp_path):
    """status --deep returns the aggregate situational picture in one call."""
    from regime_driver.cli import _reset_flow_registry
    monkeypatch.setenv("REGIME_FLOW_STORE", str(tmp_path / "flowstore"))
    _reset_flow_registry()
    # unreachable worker -> healthy=False but aggregation still returns flows/tasks
    res = runner.invoke(app, [
        "status", "--deep", "--json", "--base", "http://127.0.0.1:1",
        "--tasks-dir", str(tmp_path / "tasks")])
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["healthy"] is False
    assert "flows" in data and "tasks" in data
    assert "sessions" in data and data["busy_sessions"] == 0  # degraded worker -> empty sessions
    # with a reporter journal: rollup surfaced from disk (B2 regression)
    from regime_driver.app.reporter import Reporter
    rep = Reporter(journal_path=tmp_path / "j.jsonl")
    rep.ingest(kind="outcome", wf_id="w1", outcome="complete")
    rep.close()
    res2 = runner.invoke(app, [
        "status", "--deep", "--json", "--base", "http://127.0.0.1:1",
        "--reporter", str(tmp_path / "j.jsonl")])
    assert res2.exit_code == 0, res2.output
    data2 = json.loads(res2.output)
    assert data2["reporter"]["records"] == 1
    assert data2["reporter"]["rollup"]


def test_status_deep_reporter_rollup(tmp_path):
    """--deep --reporter must surface the journal's rollup (not empty)."""
    from regime_driver.app.reporter import Reporter
    rep = Reporter(journal_path=tmp_path / "j.jsonl")
    rep.ingest(kind="outcome", wf_id="w1", outcome="complete")
    rep.ingest(kind="outcome", wf_id="w1", outcome="complete")
    rep.ingest(kind="node_enter", wf_id="w1", node="a")
    rep.close()
    res = runner.invoke(app, [
        "status", "--deep", "--json", "--base", "http://127.0.0.1:1",
        "--reporter", str(tmp_path / "j.jsonl")])
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    rep_out = data["reporter"]
    assert rep_out["records"] == 3
    assert rep_out["rollup"]  # non-empty rollup reflects on-disk journal


def test_doctor_readonly_reports_unhealthy():
    # doctor is read-only; against an unreachable worker it reports ok=False (exit 1)
    res = runner.invoke(app, ["doctor", "--base", "http://127.0.0.1:1", "--json"])
    assert res.exit_code == 1
    data = json.loads(res.output)
    assert data["ok"] is False
    assert data["model"] == "deepseek-api/deepseek-v4-flash"
    assert data["provider"] == "deepseek-api"


def test_doctor_env_readiness_advisory_does_not_gate():
    """Deployment UX (WORK_PLAN8): doctor's environment detection (docker /
    opencode / conda / platform) is ADVISORY — it informs the user which
    deployment path their machine supports, but a missing docker/conda must NOT
    fail the doctor run (host mode works without either)."""
    res = runner.invoke(app, ["doctor", "--base", "http://127.0.0.1:1", "--json"])
    data = json.loads(res.output)
    checks = {c["check"]: c for c in data["checks"]}
    assert "docker available" in checks
    assert "opencode available" in checks
    assert "conda available" in checks
    assert "platform" in checks
    assert all(c["advisory"] is True
               for c in checks.values() if c["check"] in (
                   "docker available", "opencode available",
                   "conda available", "docker mirror set", "platform"))
    # worker-unhealthy still gates (exit 1), but the advisory env facts did not
    # add their own failures
    assert data["ok"] is False  # only the worker-health failure
    failers = [c for c in data["checks"] if not c["ok"] and not c.get("advisory")]
    assert all("worker health" in c["check"] or "version" in c["check"]
               for c in failers)


def test_doctor_session_hygiene_warns_on_low_threshold(monkeypatch):
    """with a tiny threshold, doctor must flag accumulated sessions (ok=False)."""
    monkeypatch.setenv("REGIME_SESSION_HYGIENE_THRESHOLD", "1")
    # Force a healthy fake client instead of the real worker.
    import regime_driver.cli as cli

    class _Fake:
        def health(self):
            return True

        def list_sessions(self):
            return [{"id": "a"}, {"id": "b"}]

    original = cli.OpenCodeClient
    cli.OpenCodeClient = lambda base, timeout: _Fake()  # noqa: E731
    try:
        res = runner.invoke(app, ["doctor", "--base", "http://127.0.0.1:9", "--json"])
    finally:
        cli.OpenCodeClient = original
    assert res.exit_code == 1  # advisory hygiene warning flips the gate
    data = json.loads(res.output)
    hygiene = [c for c in data["checks"] if c["check"] == "session hygiene"]
    assert hygiene and hygiene[0]["ok"] is False
    assert hygiene[0]["sessions"] == 2
    assert "cleanup advised" in hygiene[0]["detail"]
    assert "--cleanup" in hygiene[0]["detail"]


def test_doctor_session_hygiene_ok_below_threshold(monkeypatch):
    """pass path: sessions below threshold keep doctor green."""
    monkeypatch.setenv("REGIME_SESSION_HYGIENE_THRESHOLD", "100")
    import regime_driver.cli as cli

    class _Fake:
        def health(self):
            return True

        def list_sessions(self):
            return [{"id": "a"}]

    original = cli.OpenCodeClient
    cli.OpenCodeClient = lambda base, timeout: _Fake()  # noqa: E731
    try:
        res = runner.invoke(app, ["doctor", "--base", "http://127.0.0.1:9", "--json"])
    finally:
        cli.OpenCodeClient = original
    data = json.loads(res.output)
    hygiene = [c for c in data["checks"] if c["check"] == "session hygiene"]
    assert hygiene and hygiene[0]["ok"] is True
    assert hygiene[0]["sessions"] == 1


def test_doctor_survives_bad_env(monkeypatch):
    """doctor is read-only and must never crash on an invalid REGIME_* value."""
    monkeypatch.setenv("REGIME_REQUEST_TIMEOUT", "5")  # below ge=10 -> ValidationError
    res = runner.invoke(app, ["doctor", "--base", "http://127.0.0.1:1", "--json"])
    assert res.exit_code == 1  # reports unhealthy worker, does not traceback
    data = json.loads(res.output)
    assert data["ok"] is False
    assert "worker health" in [c["check"] for c in data["checks"]]


def test_version_compatible_major_minor():
    from regime_driver.infra.opencode import _version_compatible
    assert _version_compatible("1.18.11", "1.18.11")
    assert _version_compatible("1.18.4", "1.18.11")   # patch drift is safe
    assert not _version_compatible("1.19.0", "1.18.11")
    assert not _version_compatible("2.0.0", "1.18.11")
    assert _version_compatible("1.18", "1.18.11")     # server reports major.minor only


def test_doctor_version_drift_flags(monkeypatch):
    """A worker reporting an incompatible major.minor must flip the version check."""
    import regime_driver.cli as cli

    class _Fake:
        def health(self):
            return True

        def check_version(self, supported=None):
            return False, "2.0.0"

        def list_sessions(self):
            return []

    original = cli.OpenCodeClient
    cli.OpenCodeClient = lambda base, timeout: _Fake()  # noqa: E731
    try:
        res = runner.invoke(app, ["doctor", "--base", "http://127.0.0.1:9", "--json"])
    finally:
        cli.OpenCodeClient = original
    data = json.loads(res.output)
    ver = [c for c in data["checks"] if c["check"] == "opencode version"]
    assert ver and ver[0]["ok"] is False
    assert "drift" in ver[0]["detail"]


# -- regime (whole operating rule) CLI ----------------------------------------

_REGIME_SPEC = {
    "name": "cli-regime",
    "flow": {"entry": "a", "nodes": [
        {"id": "a", "desc": "干", "role": "developer", "type": "agent"},
    ]},
    "roles": {
        "developer": {"agent": "developer"},
        "reviewer": {"agent": "reviewer"},
    },
    "watchdog": {"soft_sec": 30, "hard_sec": 600},
    "handover": {"soft_fraction": 0.4, "hard_fraction": 0.8},
}


def test_regime_design_inline_registers():
    r1 = runner.invoke(app, ["regime", "design", "cli-regime",
                             json.dumps(_REGIME_SPEC, ensure_ascii=False), "--json"])
    assert r1.exit_code == 0
    assert json.loads(r1.output)["ok"] is True
    r2 = runner.invoke(app, ["regime", "list", "--json"])
    names = [e["name"] for e in json.loads(r2.output)["regimes"]]
    assert "cli-regime" in names


def test_regime_inspect_shows_components():
    runner.invoke(app, ["regime", "design", "cli-regime",
                        json.dumps(_REGIME_SPEC, ensure_ascii=False)])
    res = runner.invoke(app, ["regime", "inspect", "cli-regime", "--json"])
    assert res.exit_code == 0
    d = json.loads(res.output)
    assert d["name"] == "cli-regime"
    assert d["has_watchdog"] is True
    assert d["has_handover"] is True


def test_regime_design_rejects_invalid_watchdog():
    bad = dict(_REGIME_SPEC, watchdog={"soft_sec": -5})
    res = runner.invoke(app, ["regime", "design", "bad-regime",
                              json.dumps(bad, ensure_ascii=False), "--json"])
    assert res.exit_code == 1
    assert json.loads(res.output)["ok"] is False


def test_regime_load_file_then_reload(tmp_path):
    p = tmp_path / "r.json"
    p.write_text(json.dumps(_REGIME_SPEC, ensure_ascii=False), encoding="utf-8")
    r1 = runner.invoke(app, ["regime", "load", str(p), "--json"])
    assert r1.exit_code == 0
    assert json.loads(r1.output)["ok"] is True
    # reload bumps the version
    ins1 = json.loads(runner.invoke(app, ["regime", "inspect", "cli-regime", "--json"]).output)
    runner.invoke(app, ["regime", "reload", "cli-regime"])
    ins2 = json.loads(runner.invoke(app, ["regime", "inspect", "cli-regime", "--json"]).output)
    assert ins2["version"] > ins1["version"]


def test_regime_rm_is_write_gated(monkeypatch):
    monkeypatch.setenv("REGIME_PERMISSION_CEILING", "read")
    res = runner.invoke(app, ["regime", "rm", "cli-regime", "--perm", "run"])
    assert res.exit_code == 1
    assert "permission denied" in res.output


def test_regime_design_is_write_gated(monkeypatch):
    monkeypatch.setenv("REGIME_PERMISSION_CEILING", "read")
    res = runner.invoke(app, ["regime", "design", "x",
                              json.dumps(_REGIME_SPEC, ensure_ascii=False), "--perm", "run"])
    assert res.exit_code == 1
    assert "permission denied" in res.output


def test_regime_run_unknown_name_fails():
    res = runner.invoke(app, ["run", "task", "--regime-name", "nope"])
    assert res.exit_code == 1
    assert "unknown regime" in res.output


def test_regime_run_named_regime_uses_registry_store():
    """B1: run --regime-name must resolve against the SAME persistent registry
    the design command wrote to (not a fresh empty one), assembling the whole
    operating rule into the driver."""
    import regime_driver.cli as cli

    r1 = runner.invoke(app, ["regime", "design", "cli-regime",
                             json.dumps(_REGIME_SPEC, ensure_ascii=False)])
    assert r1.exit_code == 0
    captured = {}
    original = cli._run_impl

    def spy(driver, ledger, sm, context, title, json_out):
        captured["flow"] = sm.flow_name
        captured["watchdog"] = driver.watchdog.policy is not None
        captured["roles"] = sorted(driver.roles.ids())
        # do NOT actually run (no worker round-trip needed for the resolution check)

    cli._run_impl = spy
    try:
        res = runner.invoke(app, ["run", "task", "--regime-name", "cli-regime",
                                  "--no-preflight"])
    finally:
        cli._run_impl = original
    assert res.exit_code == 0, res.output
    assert captured.get("flow") == "cli-regime"
    assert captured.get("watchdog") is True
    assert captured.get("roles") == ["developer", "reviewer"]


def test_regime_run_with_flow_uses_resolved_sm():
    """B2: run --flow must drive the preflighted named flow, not the default."""
    import regime_driver.cli as cli

    compact = ('{"entry":"start","nodes":['
               '{"id":"start","desc":"理解","role":"developer","type":"agent","next":null}]}')
    r0 = runner.invoke(app, ["flow", "design", "mini", compact])
    assert r0.exit_code == 0
    captured = {}
    original = cli._run_impl

    def spy(driver, ledger, sm, context, title, json_out):
        captured["sm"] = sm.flow_name
        # do NOT actually run

    cli._run_impl = spy
    try:
        res = runner.invoke(app, ["run", "task", "--flow", "mini", "--no-preflight"])
    finally:
        cli._run_impl = original
    assert res.exit_code == 0, res.output
    assert captured.get("sm") == "mini"


def test_regime_run_async_forwards_regime_name():
    """W1: run --async must forward --regime-name to the background job."""
    from regime_driver.cli import _submit_job

    captured = {}
    original = _submit_job

    def spy(job_type, argv, **kw):
        captured["argv"] = argv
        return {"id": "j1", "pid": 1, "status": "running"}

    import regime_driver.cli as cli
    cli._submit_job = spy
    try:
        res = runner.invoke(app, ["run", "task", "--regime-name", "cli-regime",
                                  "--async", "--perm", "run"])
    finally:
        cli._submit_job = original
    assert res.exit_code == 0
    assert "--regime-name" in captured["argv"]
    assert "cli-regime" in captured["argv"]


def test_run_many_regime_name_builds_cluster_from_regime(monkeypatch):
    """1d: run-many --regime-name resolves the named regime and builds the
    cluster via StatechartCluster.from_regime, handing the whole operating rule
    (flow + roles + watchdog + handover) to every parallel workflow."""
    import types

    from regime_driver.app.statechart_cluster import StatechartCluster
    from regime_driver.core.models import Outcome

    r1 = runner.invoke(app, ["regime", "design", "cli-regime",
                             json.dumps(_REGIME_SPEC, ensure_ascii=False)])
    assert r1.exit_code == 0

    captured = {}
    orig_from_regime = StatechartCluster.from_regime

    def spy_from_regime(cls, regime, settings, client, ledger=None,
                        reporter=None, enforce_invariants=True, **kw):
        captured["regime"] = regime
        c = orig_from_regime(regime, settings, client, ledger, reporter,
                             enforce_invariants, **kw)
        c.run_all = lambda tasks, timeout_sec=None: {
            k: (Outcome.COMPLETE, "wrap", None) for k in tasks}
        orig_add = c.add_workflow

        def spy_add(wid, s, sm, roles=None, context_policy=None):
            captured["sm"] = sm
            captured["roles"] = roles
            captured["handover"] = context_policy
            return orig_add(wid, s, sm, roles=roles, context_policy=context_policy)

        c.add_workflow = spy_add
        return c

    monkeypatch.setattr(StatechartCluster, "from_regime",
                        classmethod(spy_from_regime))
    res = runner.invoke(app, ["run-many", "taskA", "taskB",
                              "--regime-name", "cli-regime", "--no-preflight"])
    assert res.exit_code == 0, res.output
    assert captured.get("regime") is not None
    assert captured.get("regime").name == "cli-regime"
    assert captured.get("sm") is captured.get("regime").flow
    assert sorted(captured.get("roles").ids()) == ["developer", "reviewer"]
    assert captured.get("handover") is captured.get("regime").handover


def test_run_many_unknown_regime_name_fails():
    """1d: run-many --regime-name must fail loudly on an unknown name."""
    res = runner.invoke(app, ["run-many", "taskA", "--regime-name", "nope"])
    assert res.exit_code == 1
    assert "unknown regime" in res.output


def test_drive_many_regime_name_hands_regime_to_batch(monkeypatch, tmp_path):
    """1d: drive-many --regime-name resolves the named regime and hands it to
    the Parallel batch so every member Drive runs the same operating rule."""
    import regime_driver.parallel as parallel_mod
    from regime_driver.parallel import Parallel

    r1 = runner.invoke(app, ["regime", "design", "cli-regime",
                             json.dumps(_REGIME_SPEC, ensure_ascii=False)])
    assert r1.exit_code == 0

    captured = {}
    orig_init = Parallel.__init__

    def spy_init(self, settings, sm, reporter=None, **kw):
        captured["regime"] = kw.get("regime")
        captured["sm"] = sm
        # do not let the batch actually launch worker containers / drives
        self.sm = sm
        self.settings = settings
        self.reporter = reporter
        self.pool = None
        self.deadline_sec = kw.get("deadline_sec")
        self.meta_enabled = kw.get("meta_enabled", False)
        self.meta_model = kw.get("meta_model")
        self.regime = kw.get("regime")

    monkeypatch.setattr(Parallel, "__init__", spy_init)
    monkeypatch.setattr(parallel_mod.Parallel, "run",
                        lambda self, tasks, worker_count=None: {
                            t.task_id: _complete_result() for t in tasks})
    res = runner.invoke(app, ["drive-many", "taskA", "--regime-name", "cli-regime",
                              "--no-preflight", "--workspaces", "ws-a",
                              "--json"])
    assert res.exit_code == 0, res.output
    assert captured.get("regime") is not None
    assert captured.get("regime").name == "cli-regime"
    assert captured.get("sm") is captured.get("regime").flow


def _complete_result():
    from regime_driver.drive import DriveResult
    return DriveResult("complete", end="wrap", supervisor="workflow_done",
                       elapsed_sec=1.0)




def test_job_logs_prints_captured_output(tmp_path, monkeypatch):
    """job logs reads the --async subprocess output for after-the-fact viewing."""
    import regime_driver.infra.jobs as jobs_mod
    from regime_driver.infra.jobs import JobRegistry

    jobs_dir = tmp_path / "jobs"
    jobs_dir.mkdir()
    out = jobs_dir / "job-x.stdout.log"
    out.write_text("preflight PASSED\nwork done\n[WORK_DONE]\n", encoding="utf-8")

    # fake registry.get to find the job, and point .dir at the temp dir
    monkeypatch.setattr(JobRegistry, "get",
                        lambda self, jid: {
                            "id": jid, "status": "done", "type": "run"}
                        if jid == "job-x" else None)
    monkeypatch.setattr(JobRegistry, "__init__",
                        lambda self, dir=None: setattr(self, "dir", jobs_dir))

    res = runner.invoke(app, ["job", "logs", "job-x", "--tail", "2"])
    assert res.exit_code == 0, res.output
    assert "work done" in res.output
    assert "preflight PASSED" not in res.output  # --tail 2 keeps last 2

    res_json = runner.invoke(app, ["job", "logs", "job-x", "--json"])
    assert res_json.exit_code == 0
    data = json.loads(res_json.output)
    assert data["id"] == "job-x"
    assert "work done" in "\n".join(data["lines"])

    # unknown job -> clean failure
    bad = runner.invoke(app, ["job", "logs", "nope"])
    assert bad.exit_code != 0
