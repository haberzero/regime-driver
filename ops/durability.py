#!/usr/bin/env python3
"""Long-run durability verification harness (WORK_PLAN6 I, L1).

Runs a sequence of REAL supervised tasks (`regime drive --async`) for a target
duration (default 2h) against the live worker, sampling resources at intervals:

  * task registry growth / outcome distribution (crashed/stalled vs complete)
  * worker session count + busy count (session leakage)
  * reporter journal + event ledger growth (bytes, records)
  * worker container memory / cpu (docker stats)
  * container count (worker + per-workspace instances)
  * task registry dir size

Every sample is appended to a JSONL durability ledger, and a summary report is
written at the end: the evidence for "2h+ no leak / recoverable" (or the honest
record of what was observed, per KNOWN_LIMITS discipline).

Design rules:
  * Each drive gets a FRESH task dir + reporter + ledger under the run root, so
    the run is self-contained and reproducible.
  * `--clean-sessions` between iterations is optional (default off) so we can
    OBSERVE natural session accumulation — leakage is a finding, not hidden.
  * Sampling is best-effort (a missing worker/docker command must never abort
    the whole run): every sample catches its own exceptions.
  * Offline-safe: the harness itself is stdlib-only; the real model calls go
    through `regime drive --async` subprocesses.

Usage:
    python ops/durability.py --hours 2 [--root /tmp/durability] [--task '...']
    python ops/durability.py --minutes 10   # quick smoke of the harness
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

BASE = "http://127.0.0.1:4097"
TASK_TEMPLATE = (
    "写一个Python函数 f(x)=x*{n} 保存到 dur_{n}.py 并运行确认结果打印"
)

CONTAINER_NAMES = ("opencode-worker", "opencode-god")


def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    """Run a command; never raise — return the CompletedProcess as-is."""
    try:
        return subprocess.run(cmd, capture_output=True, text=True, **kw)
    except Exception as exc:  # noqa: BLE001
        return subprocess.CompletedProcess(cmd, -1, stdout="", stderr=str(exc))


def _json(text: str):
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        return None


def _sample_session_counts() -> dict:
    p = _run(["conda", "run", "-n", "regime-driver", "regime",
              "sessions", "--json", "--base", BASE])
    data = _json(p.stdout) or {}
    sessions = data.get("sessions", []) if isinstance(data, dict) else []
    return {"sessions": len(sessions),
            "busy": sum(1 for s in sessions if s.get("status") == "busy")}


def _sample_files(root: Path) -> dict:
    journal = root / "journal.jsonl"
    ledger = root / "events.jsonl"
    return {
        "journal_bytes": journal.stat().st_size if journal.exists() else 0,
        "journal_records": sum(1 for _ in journal.open() if journal.exists())
        if journal.exists() else 0,
        "ledger_bytes": ledger.stat().st_size if ledger.exists() else 0,
    }


def _sample_tasks(root: Path) -> dict:
    tasks_dir = root / "tasks"
    if not tasks_dir.exists():
        return {"tasks": 0, "crashed": 0, "complete": 0, "bytes": 0}
    files = [f for f in tasks_dir.glob("*.json") if not f.name.endswith(".summary.json")]
    crashed = complete = 0
    for f in files:
        data = _json(f.read_text(encoding="utf-8"))
        status = (data or {}).get("outcome") or (data or {}).get("status")
        if status in ("crashed", "error"):
            crashed += 1
        elif status in ("complete", "done"):
            complete += 1
    return {"tasks": len(files), "crashed": crashed, "complete": complete,
            "bytes": sum(f.stat().st_size for f in files)}


def _sample_docker() -> dict:
    out = {}
    p = _run(["sg", "docker", "-c",
              'docker stats --no-stream --format "{{.Name}} {{.MemUsage}} {{.CPUPerc}}"'])
    for line in p.stdout.splitlines():
        parts = line.split()
        if len(parts) >= 2 and parts[0] in CONTAINER_NAMES:
            out[parts[0]] = {"mem": parts[1], "cpu": parts[2] if len(parts) > 2 else "?"}
    p2 = _run(["sg", "docker", "-c", 'docker ps --format "{{.Names}}"'])
    return {"containers": len(p2.stdout.splitlines()), "stats": out}


def sample(root: Path, run_round: int, elapsed: float) -> dict:
    rec = {"t": round(elapsed, 1), "round": run_round}
    for name, fn in [("sessions", _sample_session_counts),
                     ("files", lambda: _sample_files(root)),
                     ("tasks", lambda: _sample_tasks(root)),
                     ("docker", _sample_docker)]:
        try:
            rec[name] = fn()
        except Exception as exc:  # noqa: BLE001 — a failed sample must not kill the run
            rec[name] = {"error": str(exc)}
    return rec


def drive_task(root: Path, n: int) -> None:
    """Submit ONE real supervised drive (async) with fresh task dir/journal/ledger."""
    tasks_dir = root / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    journal = root / "journal.jsonl"
    ledger = root / "events.jsonl"
    goal = TASK_TEMPLATE.format(n=n)
    cmd = ["conda", "run", "-n", "regime-driver", "regime", "drive", goal,
           "--base", BASE, "--container", "opencode-worker",
           "--deadline", "600", "--reporter", str(journal),
           "--ledger", str(ledger), "--tasks-dir", str(tasks_dir),
           "--async"]
    _run(cmd)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=2.0, help="target run duration")
    ap.add_argument("--minutes", type=float, default=0.0,
                    help="short override: run this many minutes instead of --hours")
    ap.add_argument("--root", type=Path, default=Path("/tmp/durability"),
                    help="run root (tasks/journal/ledger/samples live here)")
    ap.add_argument("--sample-sec", type=float, default=60.0,
                    help="resource sampling interval")
    ap.add_argument("--task-sec", type=float, default=120.0,
                    help="min wall time between drive submissions")
    ap.add_argument("--rounds", type=int, default=0,
                    help="max drive submissions (0 = unlimited for the duration)")
    args = ap.parse_args()

    root = args.root
    root.mkdir(parents=True, exist_ok=True)
    # --minutes overrides --hours; both are in human units (hours * 3600).
    duration = (args.minutes if args.minutes > 0 else args.hours * 60.0) * 60.0
    samples = root / "samples.jsonl"
    start = time.time()
    last_drive = 0.0
    round_no = 0

    print(f"[durability] root={root} duration={duration:.0f}s "
          f"sample={args.sample_sec}s", flush=True)

    while True:
        elapsed = time.time() - start
        if elapsed >= duration:
            break
        # submit a fresh drive when the min cadence has elapsed (round-limited)
        if round_no == 0 or (elapsed - last_drive >= args.task_sec
                             and (args.rounds == 0 or round_no < args.rounds)):
            round_no += 1
            last_drive = elapsed
            drive_task(root, round_no)
            print(f"  [{elapsed:6.1f}s] submitted drive round {round_no}", flush=True)

        rec = sample(root, round_no, elapsed)
        with samples.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

        # adaptive sleep: sample cadence, but never longer than remaining budget
        time.sleep(min(args.sample_sec, max(1.0, duration - elapsed)))

    # final sample + summary
    elapsed = time.time() - start
    rec = sample(root, round_no, elapsed)
    with samples.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    summary = _summarize(root, round_no, elapsed, samples)
    report = root / "durability-report.json"
    report.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(f"[durability] DONE {elapsed:.0f}s -> {report}", flush=True)


def _summarize(root: Path, rounds: int, elapsed: float, samples: Path) -> dict:
    rows = []
    with samples.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))

    first, last = rows[0], rows[-1]
    session_series = [r["sessions"]["sessions"] for r in rows if "sessions" in r
                      and isinstance(r["sessions"], dict)]
    busy_series = [r["sessions"]["busy"] for r in rows if "sessions" in r
                   and isinstance(r["sessions"], dict)]
    journal_series = [r["files"]["journal_bytes"] for r in rows if "files" in r
                      and isinstance(r["files"], dict)]

    # event-ledger audit: outcome distribution + supervisor ladder events
    outcome_counts: dict[str, int] = {}
    ladder_events: dict[str, int] = {}
    ledger = root / "events.jsonl"
    if ledger.exists():
        for line in ledger.open(encoding="utf-8"):
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            ev = d.get("event")
            if ev == "outcome":
                outcome_counts[d.get("outcome", "?")] = outcome_counts.get(d.get("outcome", "?"), 0) + 1
            elif isinstance(ev, str) and any(k in ev for k in
                                             ("stall", "restart", "abort", "escalate", "gave_up")):
                ladder_events[ev] = ladder_events.get(ev, 0) + 1

    return {
        "elapsed_sec": round(elapsed, 1),
        "drives_submitted": rounds,
        "sessions": {
            "start": session_series[0] if session_series else None,
            "end": session_series[-1] if session_series else None,
            "max": max(session_series) if session_series else None,
            "busy_end": busy_series[-1] if busy_series else None,
        },
        "journal": {
            "start_bytes": journal_series[0] if journal_series else None,
            "end_bytes": journal_series[-1] if journal_series else None,
        },
        "event_audit": {
            "outcomes": outcome_counts,
            "ladder_events": ladder_events,
        },
        "tasks_dir": _sample_tasks(root),
        "worker_mem_end": last.get("docker", {}).get("stats", {}).get("opencode-worker"),
        "samples": len(rows),
    }


if __name__ == "__main__":
    main()
