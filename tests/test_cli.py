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


def test_doctor_readonly_reports_unhealthy():
    # doctor is read-only; against an unreachable worker it reports ok=False (exit 1)
    res = runner.invoke(app, ["doctor", "--base", "http://127.0.0.1:1", "--json"])
    assert res.exit_code == 1
    data = json.loads(res.output)
    assert data["ok"] is False
    assert data["model"] == "my-opencode-go/deepseek-v4-flash"
    assert data["provider"] == "my-opencode-go"
