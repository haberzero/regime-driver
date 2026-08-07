"""Tests for the oc-task registry reader (infra/oc_tasks.py)."""

from __future__ import annotations

import json

from regime_driver.infra.oc_tasks import load_tasks


def test_load_tasks_empty(tmp_path) -> None:
    assert load_tasks(tmp_path) == []


def test_load_tasks_missing_dir() -> None:
    assert load_tasks("/no/such/dir") == []


def test_load_tasks_derives_done_from_summary(tmp_path) -> None:
    tid = "task-1"
    (tmp_path / f"{tid}.json").write_text(json.dumps({
        "id": tid, "goal": "do thing", "status": "running",
        "pid": 999_999_999, "created": "2026-01-01T00:00:00",
        "summary_file": str(tmp_path / f"{tid}.summary.json"),
    }), encoding="utf-8")
    (tmp_path / f"{tid}.summary.json").write_text(
        json.dumps({"outcome": "complete"}), encoding="utf-8")
    tasks = load_tasks(tmp_path)
    assert len(tasks) == 1
    assert tasks[0]["id"] == tid
    assert tasks[0]["status"] == "done"
    assert tasks[0]["outcome"] == "complete"


def test_load_tasks_crashed_when_no_pid_no_summary(tmp_path) -> None:
    tid = "task-2"
    (tmp_path / f"{tid}.json").write_text(json.dumps({
        "id": tid, "goal": "x", "status": "running", "pid": None,
    }), encoding="utf-8")
    tasks = load_tasks(tmp_path)
    assert tasks[0]["status"] == "crashed"


def test_load_tasks_skips_summary_files(tmp_path) -> None:
    (tmp_path / "task-a.json").write_text(
        json.dumps({"id": "task-a", "status": "running", "pid": None}), encoding="utf-8")
    (tmp_path / "task-a.summary.json").write_text(
        json.dumps({"outcome": "complete"}), encoding="utf-8")
    tasks = load_tasks(tmp_path)
    assert len(tasks) == 1
