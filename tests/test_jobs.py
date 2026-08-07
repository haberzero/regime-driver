"""Tests for the async job registry (infra/jobs.py)."""

from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

from regime_driver.infra.jobs import JobRegistry, JobStatus, public_record


@pytest.fixture
def jobs_dir(tmp_path: Path) -> Path:
    return tmp_path / "jobs"


def _write_result(jobs_dir: Path, job_id: str, data: dict) -> None:
    (jobs_dir / f"{job_id}.result.json").write_text(
        json.dumps(data), encoding="utf-8")


def test_create_persists_record(jobs_dir: Path) -> None:
    reg = JobRegistry(jobs_dir)
    # simulate: create without launching by calling internals
    job_id = "j1"
    record = {
        "id": job_id, "type": "run", "title": "t", "status": JobStatus.RUNNING,
        "pid": None, "created_at": time.time(), "started_at": None,
        "finished_at": None, "ledger": None,
        "result_path": str(jobs_dir / f"{job_id}.result.json"),
        "out_path": str(jobs_dir / f"{job_id}.stdout.log"), "argv": ["run", "x"],
    }
    reg._save([record])
    assert reg.get(job_id)["id"] == job_id
    assert reg.list()[0]["id"] == job_id


def test_status_refresh_to_done(jobs_dir: Path) -> None:
    reg = JobRegistry(jobs_dir)
    job_id = "j2"
    # pid that cannot exist -> subprocess exited
    record = {
        "id": job_id, "type": "run", "title": "t", "status": JobStatus.RUNNING,
        "pid": 999_999_999, "created_at": time.time(), "started_at": time.time(),
        "finished_at": None, "ledger": None,
        "result_path": str(jobs_dir / f"{job_id}.result.json"),
        "out_path": str(jobs_dir / f"{job_id}.stdout.log"), "argv": [],
    }
    reg._save([record])
    _write_result(jobs_dir, job_id, {"outcome": "complete", "elapsed_sec": 1.0})
    got = reg.get(job_id)
    assert got["status"] == JobStatus.DONE
    assert got["result"] == {"outcome": "complete", "elapsed_sec": 1.0}


def test_status_refresh_failed_when_no_result(jobs_dir: Path) -> None:
    reg = JobRegistry(jobs_dir)
    job_id = "j3"
    record = {
        "id": job_id, "type": "run-many", "title": "", "status": JobStatus.RUNNING,
        "pid": 999_999_999, "created_at": time.time(), "started_at": time.time(),
        "finished_at": None, "ledger": None,
        "result_path": str(jobs_dir / f"{job_id}.result.json"),
        "out_path": str(jobs_dir / f"{job_id}.stdout.log"), "argv": [],
    }
    reg._save([record])
    assert reg.get(job_id)["status"] == JobStatus.FAILED


def test_launch_subprocess_writes_result(jobs_dir: Path) -> None:
    """The background subprocess really writes a parseable result file."""
    reg = JobRegistry(jobs_dir)
    job_id = "j4"
    argv = ["__probe__"]
    record = {
        "id": job_id, "type": "run", "title": "", "status": JobStatus.RUNNING,
        "pid": None, "created_at": time.time(), "started_at": None,
        "finished_at": None, "ledger": None,
        "result_path": str(jobs_dir / f"{job_id}.result.json"),
        "out_path": str(jobs_dir / f"{job_id}.stdout.log"), "argv": argv,
    }
    reg._save([record])
    # spawn a subprocess that writes the result file (stand-in for the CLI)
    code = (
        f"import json, sys; "
        f"json.dump({{'outcome':'complete'}}, open({str(jobs_dir / (job_id + '.result.json'))!r},'w'))"
    )
    proc = __import__("subprocess").Popen(
        [sys.executable, "-c", code], start_new_session=True)
    proc.wait()
    got = reg.get(job_id)
    assert got["status"] == JobStatus.DONE
    assert got["result"] == {"outcome": "complete"}


def test_refresh_persists_status_to_disk(jobs_dir: Path) -> None:
    """After get() marks a job done, the registry file must reflect it (no stale RUNNING)."""
    reg = JobRegistry(jobs_dir)
    job_id = "j6"
    record = {
        "id": job_id, "type": "run", "title": "t", "status": JobStatus.RUNNING,
        "pid": 999_999_999, "created_at": time.time(), "started_at": time.time(),
        "finished_at": None, "ledger": None,
        "result_path": str(jobs_dir / f"{job_id}.result.json"),
        "out_path": str(jobs_dir / f"{job_id}.stdout.log"), "argv": [],
    }
    reg._save([record])
    _write_result(jobs_dir, job_id, {"outcome": "complete"})
    assert reg.get(job_id)["status"] == JobStatus.DONE
    # a fresh registry instance must read the persisted status, not recompute
    persisted = json.loads((jobs_dir / "registry.json").read_text(encoding="utf-8"))[0]
    assert persisted["status"] == JobStatus.DONE
    assert persisted["result"] == {"outcome": "complete"}
    assert persisted["finished_at"] is not None
    # and a fresh instance agrees
    assert JobRegistry(jobs_dir).get(job_id)["status"] == JobStatus.DONE


def test_public_record_strips_internal_fields(jobs_dir: Path) -> None:
    reg = JobRegistry(jobs_dir)
    record = {
        "id": "j5", "type": "run", "title": "t", "status": JobStatus.RUNNING,
        "pid": 123, "created_at": 1, "started_at": None, "finished_at": None,
        "ledger": None, "result_path": "/tmp/x", "out_path": "/tmp/y",
        "argv": ["run", "z"], "result": None,
    }
    pub = public_record(record)
    assert "argv" not in pub
    assert "result_path" not in pub
    assert pub["id"] == "j5"
