"""CLI command-level tests (G14): exercise real commands, not just helpers.

Covers commands that need no live worker: validate --json/--deep, preflight
(offline MockClient), report (empty), and the mandatory permission gate.
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from regime_driver.cli import app

runner = CliRunner()


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


def test_doctor_readonly_reports_unhealthy():
    # doctor is read-only; against an unreachable worker it reports ok=False (exit 1)
    res = runner.invoke(app, ["doctor", "--base", "http://127.0.0.1:1", "--json"])
    assert res.exit_code == 1
    data = json.loads(res.output)
    assert data["ok"] is False
    assert data["model"] == "my-opencode-go/deepseek-v4-flash"
    assert data["provider"] == "my-opencode-go"
