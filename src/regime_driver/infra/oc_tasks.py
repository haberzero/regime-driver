"""Reader for the oc-task supervised-task registry (ops/tasks/*.json).

`ops/oc-task.py submit` runs each autonomous goal as an independent supervisor
process and records it in ``ops/tasks/<id>.json``. This module reads that
registry and derives each task's live status (running/done/crashed/stopped)
the same way oc-task does, so the report bus / `regime report` can present the
macro supervised-task board alongside workflow reports — one query surface.

It never mutates the registry (read-only; lifecycle stays with oc-task.py).
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def _pid_alive(pid) -> bool:
    if not pid:
        return False
    try:
        os.kill(int(pid), 0)
        return True
    except (OSError, ValueError, TypeError):
        return False


def _derive(t: dict) -> tuple[str, str | None]:
    """Return (live_status, outcome) mirroring oc-task.py derive()."""
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


def load_tasks(tasks_dir: str | Path | None) -> list[dict]:
    """Load and normalize all supervised-task records (empty if dir unset/missing)."""
    if not tasks_dir:
        return []
    d = Path(tasks_dir)
    if not d.is_dir():
        return []
    out = []
    for path in sorted(d.glob("*.json")):
        if path.name.endswith(".summary.json"):
            continue
        try:
            rec = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(rec, dict):
            continue
        status, outcome = _derive(rec)
        out.append({
            "id": rec.get("id") or path.stem,
            "goal": (rec.get("goal") or "")[:60],
            "status": status,
            "outcome": outcome,
            "pid": rec.get("pid"),
            "created": rec.get("created"),
            "deadline": rec.get("deadline"),
        })
    return out
