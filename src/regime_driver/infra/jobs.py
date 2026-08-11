"""Job registry for non-blocking `regime run/run-many --async`.

An async run submits a background subprocess and returns a handle immediately.
This registry persists job records on disk so a *later* CLI invocation can
query them (`regime job list` / `regime job status <id>`), independent of the
process that launched the job.

Layout (under the jobs dir, default ``~/.regime/jobs``, override with
``$REGIME_JOBS_DIR``):

    registry.json      the full list of job records
    <id>.result.json   JSON written by the async subprocess when it finishes
    <id>.stdout.log    captured stdout/stderr of the background process

Only the stdlib is used so the registry works offline and in containers.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import uuid
from pathlib import Path
from typing import Any

from .proc import pid_alive


class JobStatus:
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


class JobRegistry:
    """A small JSON-file-backed registry of async regime jobs."""

    def __init__(self, dir: str | Path | None = None) -> None:
        self.dir = Path(
            dir or os.environ.get("REGIME_JOBS_DIR") or Path.home() / ".regime" / "jobs"
        )
        self.dir.mkdir(parents=True, exist_ok=True)
        self.file = self.dir / "registry.json"

    # -- persistence --------------------------------------------------------

    def _load(self) -> list[dict]:
        if not self.file.exists():
            return []
        try:
            with self.file.open(encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    def _save(self, records: list[dict]) -> None:
        tmp = self.file.with_suffix(".tmp")
        with tmp.open("w", encoding="utf-8") as fh:
            json.dump(records, fh, ensure_ascii=False, indent=2)
        tmp.replace(self.file)

    # -- lifecycle ----------------------------------------------------------

    def create(self, job_type: str, argv: list[str], *, ledger: str | None = None,
               title: str = "") -> dict:
        """Record a new job, launch its background subprocess, return the record."""
        job_id = time.strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:6]
        result_path = self.dir / f"{job_id}.result.json"
        out_path = self.dir / f"{job_id}.stdout.log"
        record = {
            "id": job_id,
            "type": job_type,
            "title": title,
            "status": JobStatus.RUNNING,
            "pid": None,
            "created_at": time.time(),
            "started_at": None,
            "finished_at": None,
            "ledger": ledger,
            "result_path": str(result_path),
            "out_path": str(out_path),
            "argv": argv,
        }
        records = self._load()
        records.insert(0, record)
        self._save(records)
        self._launch(job_id, argv, result_path, out_path)
        return self.get(job_id)

    def _launch(self, job_id: str, argv: list[str], result_path: Path, out_path: Path) -> None:
        """Spawn the CLI as a detached background process writing a result file."""
        args = [sys.executable, "-m", "regime_driver.cli", *argv, "--json"]
        try:
            with out_path.open("w", encoding="utf-8") as out_fh:
                proc = subprocess.Popen(
                    args,
                    stdout=out_fh,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                )
        except OSError as exc:
            # process failed to start: mark the job FAILED, do not leave a dead record
            self._update_record({
                "id": job_id, "status": JobStatus.FAILED, "finished_at": time.time(),
            })
            raise RuntimeError(f"failed to launch job {job_id}: {exc}") from exc
        records = self._load()
        for r in records:
            if r["id"] == job_id:
                r["pid"] = proc.pid
                r["started_at"] = time.time()
        self._save(records)

    def _refresh(self, record: dict) -> dict:
        """Update a record's status by inspecting its subprocess + result file.

        A parseable result file is authoritative for DONE (the subprocess wrote
        it last, before exiting), so it is consulted even while the pid appears
        alive (guards against pid recycling). Only a live pid with no result
        keeps the job RUNNING.
        """
        if record.get("status") != JobStatus.RUNNING:
            return record
        result_path = Path(record["result_path"])
        data = None
        if result_path.exists():
            try:
                data = json.loads(result_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                data = None
        alive = False
        if data is None and record.get("pid") is not None:
            alive = pid_alive(record["pid"])
        if data is not None or not alive:
            # subprocess exited (or already wrote its result); no result -> FAILED
            record["status"] = JobStatus.DONE if data is not None else JobStatus.FAILED
            record["result"] = data
            record["finished_at"] = time.time()
            self._update_record(record)
        return record

    def _update_record(self, updated: dict) -> None:
        """Persist a mutated record back into the registry (load, patch, save)."""
        records = self._load()
        for r in records:
            if r["id"] == updated["id"]:
                r.update(updated)
        self._save(records)

    # -- queries ------------------------------------------------------------

    def get(self, job_id: str) -> dict | None:
        for r in self._load():
            if r["id"] == job_id:
                return self._refresh(r)
        return None

    def list(self, *, include_all: bool = True) -> list[dict]:
        records = [self._refresh(r) for r in self._load()]
        if not include_all:
            records = [r for r in records if r["status"] == JobStatus.RUNNING]
        return records


def public_record(record: dict) -> dict:
    """Shape a record for machine/CLI consumption (drop internal argv/stdout paths)."""
    return {
        "id": record.get("id"),
        "type": record.get("type"),
        "title": record.get("title"),
        "status": record.get("status"),
        "pid": record.get("pid"),
        "created_at": record.get("created_at"),
        "started_at": record.get("started_at"),
        "finished_at": record.get("finished_at"),
        "ledger": record.get("ledger"),
        "result": record.get("result"),
    }
