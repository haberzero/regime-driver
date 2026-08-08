"""Task registry (first-class regime-driver component) — absorbs old oc-task.

Replaces `ops/oc-task.py` as the supervised-task registry with a single derive
implementation (killing the oc-task.derive vs oc_tasks._derive dual truth). Each
task = one independent supervisor process; records live in a JSON dir. The
report bus reads this registry directly (`regime report --tasks-dir`), so there
is exactly one task-view.

The registry is a directory of `<id>.json` records + optional `<id>.summary.json`.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from pathlib import Path

DEFAULT_TASKS_DIR = os.environ.get("REGIME_TASKS_DIR", str(Path.home() / ".regime" / "tasks"))


def _pid_alive(pid) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (PermissionError, ProcessLookupError):
        return False
    except (OSError, ValueError, TypeError):
        return False


def derive(t: dict) -> tuple[str, str | None]:
    """Single source of live task status: pid-alive -> running; summary -> done."""
    status = t.get("status", "unknown")
    outcome = t.get("outcome")
    if _pid_alive(t.get("pid")):
        return "running", outcome
    sf = t.get("summary_file")
    if sf and os.path.exists(sf):
        try:
            with open(sf, encoding="utf-8") as fh:
                data = json.loads(fh.read().strip())
            return "done", data.get("outcome")
        except (json.JSONDecodeError, OSError):
            pass
    if status == "stopped":
        return "stopped", outcome
    if status in ("done", "stopped"):
        return status, outcome
    return "crashed", outcome


class TaskRegistry:
    """Read/write the supervised-task registry (single derive)."""

    def __init__(self, tasks_dir: str | Path | None = None) -> None:
        self.dir = Path(tasks_dir or DEFAULT_TASKS_DIR)
        self.dir.mkdir(parents=True, exist_ok=True)

    def _path(self, tid: str) -> Path:
        return self.dir / f"{tid}.json"

    def submit(self, argv: list[str], *, goal: str = "", deadline: int | None = None,
               out_file: str | None = None) -> dict:
        """Submit a background task (a supervisor subprocess). Returns the record."""
        tid = f"task-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
        summary = self.dir / f"{tid}.summary.json"
        out = out_file or str(self.dir / f"{tid}.out")
        rec = {
            "id": tid, "goal": goal, "deadline": deadline, "status": "running",
            "pid": None, "summary_file": str(summary), "out_file": out,
            "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
        with open(out, "w", encoding="utf-8") as out_fh:
            proc = subprocess.Popen(argv, stdout=out_fh, stderr=subprocess.STDOUT,
                                    start_new_session=True)
        rec["pid"] = proc.pid
        self._save(rec)
        return rec

    def _save(self, rec: dict) -> None:
        (self.dir / f"{rec['id']}.json").write_text(
            json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")

    def list(self, include_all: bool = True) -> list[dict]:
        out = []
        for path in sorted(self.dir.glob("*.json")):
            if path.name.endswith(".summary.json"):
                continue
            try:
                rec = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if not isinstance(rec, dict):
                continue
            status, outcome = derive(rec)
            out.append({**rec, "status": status, "outcome": outcome})
        return out

    def get(self, tid: str) -> dict | None:
        path = self._path(tid)
        if not path.exists():
            return None
        rec = json.loads(path.read_text(encoding="utf-8"))
        status, outcome = derive(rec)
        return {**rec, "status": status, "outcome": outcome}

    def stop(self, tid: str, wait_sec: float = 3.0) -> bool:
        rec = self.get(tid)
        if rec is None:
            return False
        pid = rec.get("pid")
        if pid:
            try:
                os.kill(int(pid), 15)
                # give it a moment, then escalate to SIGKILL if it ignores SIGTERM
                end = time.time() + wait_sec
                while time.time() < end and _pid_alive(pid):
                    time.sleep(0.2)
                if _pid_alive(pid):
                    os.kill(int(pid), 9)
            except (OSError, ValueError, TypeError):
                pass
        rec["status"] = "stopped"
        self._save({k: rec[k] for k in ("id", "goal", "deadline", "status", "pid",
                                        "summary_file", "out_file", "created")})
        return True

    def logs(self, tid: str) -> str:
        rec = self.get(tid)
        if rec is None:
            return ""
        out = rec.get("out_file")
        if out and os.path.exists(out):
            try:
                return Path(out).read_text(encoding="utf-8", errors="replace")
            except OSError:
                return ""
        return "(no logs)"

    def clean(self, tid: str) -> None:
        """Delete a task's records. Refuses to clean a still-running process."""
        rec = self.get(tid)
        if rec is not None and rec.get("pid") and _pid_alive(rec.get("pid")):
            raise RuntimeError(
                f"task {tid} still running (pid {rec.get('pid')}); stop it first")
        for suffix in (".json", ".out", ".summary.json"):
            p = self.dir / f"{tid}{suffix}"
            if p.exists():
                p.unlink()
