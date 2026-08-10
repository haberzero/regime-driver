"""Tests for the supervised-task registry (task.py)."""

from __future__ import annotations

import json
from pathlib import Path

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


def test_register_reuses_task_id_for_async_child(tmp_path) -> None:
    """Async drive child reuses the parent's task id (no duplicate record)."""
    reg = TaskRegistry(tmp_path)
    parent = reg.register(goal="g", deadline=60, pid=111, out_file=str(tmp_path / "p.out"))
    # the child re-enters `regime drive` with REGIME_TASK_ID set and re-registers
    child = reg.register(goal="g", deadline=60, pid=222,
                         task_id=parent["id"])
    assert child["id"] == parent["id"]
    assert child["summary_file"] == parent["summary_file"]
    # only ONE record in the registry
    assert len(reg.list()) == 1
    # writing the summary under the shared id marks the single task done
    (tmp_path / f"{parent['id']}.summary.json").write_text(
        json.dumps({"outcome": "complete"}), encoding="utf-8")
    assert reg.get(parent["id"])["status"] == "done"


def test_submit_sets_regime_task_id_env(tmp_path) -> None:
    """submit() exports REGIME_TASK_ID so the async child reuses the task id."""
    reg = TaskRegistry(tmp_path)
    # a tiny child that echoes the env var, so we can assert it was propagated
    import sys
    rec = reg.submit([sys.executable, "-c",
                      "import os,sys; sys.stderr.write(os.environ.get('REGIME_TASK_ID',''))"],
                     goal="g")
    import time
    from regime_driver.task import _pid_alive
    for _ in range(50):
        if not _pid_alive(rec["pid"]):
            break
        time.sleep(0.1)
    text = Path(rec["out_file"]).read_text(encoding="utf-8", errors="replace") if Path(
        rec["out_file"]).exists() else ""
    assert rec["id"] in text


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
