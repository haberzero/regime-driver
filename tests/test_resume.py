"""Crash-resume support tests (app/resume.py) + drive monitor snapshot."""

from __future__ import annotations

import json

from regime_driver.app.resume import resume_context, resume_node


def _journal(path, records):
    with open(path, "w", encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps({"schema": "regime.report.v1", **rec},
                                ensure_ascii=False) + "\n")


def test_resume_node_mid_run(tmp_path):
    p = tmp_path / "j.jsonl"
    _journal(p, [
        {"kind": "node_enter", "node": "understand"},
        {"kind": "node_done", "node": "understand"},
        {"kind": "node_enter", "node": "design"},
        {"kind": "node_done", "node": "design"},
        {"kind": "node_enter", "node": "impl-core"},  # crashed here (never done)
    ])
    assert resume_node(p) == "impl-core"


def test_resume_node_first_incomplete(tmp_path):
    """The FIRST entered-but-not-done node wins (chronological replay)."""
    p = tmp_path / "j.jsonl"
    _journal(p, [
        {"kind": "node_enter", "node": "a"},
        {"kind": "node_enter", "node": "b"},  # a never done -> resume a
    ])
    assert resume_node(p) == "a"


def test_resume_none_on_complete_or_empty(tmp_path):
    p = tmp_path / "j.jsonl"
    _journal(p, [
        {"kind": "node_enter", "node": "a"},
        {"kind": "node_done", "node": "a"},
        {"kind": "outcome", "node": "a", "outcome": "complete"},
    ])
    assert resume_node(p) is None
    assert resume_node(tmp_path / "missing.jsonl") is None
    (tmp_path / "empty.jsonl").write_text("", encoding="utf-8")
    assert resume_node(tmp_path / "empty.jsonl") is None


def test_resume_context_marks_resume():
    c = resume_context("构建系统", "impl-core")
    assert "续跑" in c and "impl-core" in c and "构建系统" in c


def test_drive_monitor_writes_snapshots(tmp_path):
    """Drive's built-in monitor thread writes periodic JSONL snapshots."""
    from regime_driver.drive import Drive
    from regime_driver.infra.regime_loader import load_regime
    from regime_driver.infra.settings import Settings
    from regime_driver.testing.mock_client import MockClient

    sm = load_regime()
    client = MockClient(sm=sm)
    settings = Settings(monitor_enabled=False, poll_sec=0.1)
    mpath = tmp_path / "monitor.jsonl"
    drv = Drive(settings, sm, client, monitor_path=str(mpath),
                monitor_interval=5.0)
    res = drv.run("任务", "t")
    assert res.outcome in ("complete", "error")
    assert mpath.is_file()
    lines = mpath.read_text(encoding="utf-8").strip().splitlines()
    assert lines, "monitor must write at least one snapshot"
    rec = json.loads(lines[0])
    assert {"ts", "uptime_sec", "node", "phase", "sessions", "busy"} <= set(rec)


def test_drive_notable_summary_from_ledger(tmp_path):
    """DriveResult.notable counts recovery/error events from the ledger."""
    from regime_driver.drive import Drive
    from regime_driver.infra.ledger import Ledger
    from regime_driver.infra.regime_loader import load_regime
    from regime_driver.infra.settings import Settings
    from regime_driver.testing.mock_client import MockClient

    sm = load_regime()
    client = MockClient(sm=sm)
    settings = Settings(monitor_enabled=False, poll_sec=0.1,
                        ledger_path=str(tmp_path / "ledger.jsonl"))
    drv = Drive(settings, sm, client)
    res = drv.run("任务", "t")
    assert isinstance(res.notable, dict)
    # a clean mock run may produce zero notable events, but the field must exist
    assert "dispatch_error" in res.notable or res.notable == {}
