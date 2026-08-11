"""CLI command-level tests (G14): exercise real commands, not just helpers.

Covers commands that need no live worker: validate --json/--deep, preflight
(offline MockClient), report (empty), and the mandatory permission gate.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from regime_driver.cli import app, _reset_flow_registry

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolate_flow_registry(tmp_path, monkeypatch):
    # isolate the persistent flow store: fresh in-process registry + a temp
    # store dir, so CLI flow load/rm never touch the user's real ~/.regime/flows
    # and never leak across tests.
    monkeypatch.setenv("REGIME_FLOW_STORE", str(tmp_path / "flowstore"))
    _reset_flow_registry()
    yield
    _reset_flow_registry()


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
    res = runner.invoke(app, ["preflight", "--fault", "stall", "--json"])
    assert res.exit_code == 1
    data = json.loads(res.output)
    assert data["ok"] is False


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
    """flow design takes an inline spec (no file) and persists it (P0 god design)."""
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
                             "--preflight", "--preflight-fault", "stall", "--json"])
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
