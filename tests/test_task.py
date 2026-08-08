"""Tests for the supervised-task registry (task.py)."""

from __future__ import annotations

import json

from regime_driver.task import TaskRegistry, derive


def test_derive_done_from_summary(tmp_path) -> None:
    tid = "t1"
    (tmp_path / f"{tid}.json").write_text(json.dumps({
        "id": tid, "status": "running", "pid": 999_999_999,
        "summary_file": str(tmp_path / f"{tid}.summary.json"),
    }), encoding="utf-8")
    (tmp_path / f"{tid}.summary.json").write_text(
        json.dumps({"outcome": "complete"}), encoding="utf-8")
    assert derive(json.loads((tmp_path / f"{tid}.json").read_text()))[0] == "done"


def test_derive_crashed_when_no_pid_no_summary() -> None:
    assert derive({"id": "t", "status": "running", "pid": None})[0] == "crashed"


def test_derive_stopped() -> None:
    assert derive({"id": "t", "status": "stopped", "pid": None})[0] == "stopped"


def test_registry_list_and_status(tmp_path) -> None:
    reg = TaskRegistry(tmp_path)
    (tmp_path / "task-a.json").write_text(json.dumps({
        "id": "task-a", "status": "running", "pid": None,
        "summary_file": str(tmp_path / "task-a.summary.json")}), encoding="utf-8")
    (tmp_path / "task-a.summary.json").write_text(
        json.dumps({"outcome": "complete"}), encoding="utf-8")
    tasks = reg.list()
    assert len(tasks) == 1
    assert tasks[0]["id"] == "task-a"
    assert tasks[0]["status"] == "done"  # derived from summary, not the stale record
    assert reg.get("task-a")["outcome"] == "complete"


def test_registry_clean_removes_all_files(tmp_path) -> None:
    reg = TaskRegistry(tmp_path)
    tid = "task-b"
    (tmp_path / f"{tid}.json").write_text(json.dumps({"id": tid}), encoding="utf-8")
    (tmp_path / f"{tid}.summary.json").write_text("{}", encoding="utf-8")
    (tmp_path / f"{tid}.out").write_text("x", encoding="utf-8")
    reg.clean(tid)
    assert not (tmp_path / f"{tid}.json").exists()
    assert not (tmp_path / f"{tid}.summary.json").exists()
    assert not (tmp_path / f"{tid}.out").exists()
