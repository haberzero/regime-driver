#!/usr/bin/env python3
"""Quality-gain verification harness (WORK_PLAN6 I, L2).

Runs a suite of REAL complex engineering tasks (`regime drive --async`) against
the live worker and measures, per task:

  * outcome + elapsed (complete / timeout / blocked / crashed),
  * **host-side external test**: `docker cp` the produced module + test file
    out of the worker and re-run pytest on the host (independent of the
    worker's own run) -> N passed / failed,
  * **reviewer engagement**: reviewer_verdict / advance / gate-exhausted
    events from the event ledger (evidence the review gate did real work),
  * resource sampling (reused from ops/durability.py) + task registry growth.

The suite is `ops/quality_tasks.py`. Tasks run sequentially (one at a time)
to avoid the over-subscription that corrupted the previous steady-state run,
and so each task's artifacts can be re-verified while fresh.

Usage:
    python ops/quality_run.py --minutes 10 [--tasks graph_algos,csv_parse]
    python ops/quality_run.py --hours 2 --root /tmp/quality-run
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from quality_tasks import TASKS, QualityTask

BASE = "http://127.0.0.1:4097"
CONTAINER = "opencode-worker"
WORK_DIR = "/root/work"  # default worker cwd inside the container
HOST_PYTEST = ["conda", "run", "-n", "regime-driver", "python", "-m", "pytest"]


def _run(cmd, timeout=90.0, **kw):
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, **kw)
    except Exception as exc:  # noqa: BLE001
        return subprocess.CompletedProcess(cmd, -1, stdout="", stderr=str(exc))


def _json(text):
    try:
        out = json.loads(text)
    except Exception:  # noqa: BLE001
        return {}
    return out if isinstance(out, dict) else {}


def seed_task_files(root: Path, task: QualityTask) -> None:
    """Pre-seed files into the worker /root/work/code for refactor/fix tasks.

    Writes each `task.seed_files` entry into a host staging dir, `docker cp`s
    it into the container, and chowns to root (the worker runs as root). This
    lets tasks act on EXISTING code (refactor / bug-fix shapes) instead of only
    writing from scratch.
    """
    if not task.seed_files:
        return
    stage = root / "seeds" / task.id
    stage.mkdir(parents=True, exist_ok=True)
    for name, content in task.seed_files.items():
        (stage / name).write_text(content, encoding="utf-8")
        p = _run(["sg", "docker", "-c",
                  f"docker cp {stage / name} {CONTAINER}:/root/work/code/{name}"],
                 timeout=30.0)
        if p.returncode != 0:
            print(f"  [seed] {name}: rc={p.returncode}: {p.stderr[:200]}", flush=True)
        else:
            print(f"  [seed] {name} -> worker /root/work/code/", flush=True)


def submit_drive(root: Path, task: QualityTask, deadline: int) -> str | None:
    """Submit one supervised drive (async); return the task id (from output)."""
    tasks_dir = root / "tasks"
    tasks_dir.mkdir(parents=True, exist_ok=True)
    journal = root / "journal.jsonl"
    ledger = root / "events.jsonl"
    goal = f"[任务 {task.id}] {task.spec}"
    cmd = ["conda", "run", "-n", "regime-driver", "regime", "drive", goal,
           "--base", BASE, "--container", CONTAINER,
           "--deadline", str(deadline), "--reporter", str(journal),
           "--ledger", str(ledger), "--tasks-dir", str(tasks_dir),
           "--async", "--json"]
    if task.flow:
        cmd += ["--flow", task.flow]
    p = _run(cmd, timeout=90.0)
    if p.returncode != 0:
        print(f"  [submit] rc={p.returncode}: {p.stderr[:300]}", flush=True)
        return None
    out = _json(p.stdout)
    return out.get("task") or out.get("task_id") or out.get("id")


def wait_task(root: Path, task_id: str, timeout: float) -> dict | None:
    """Poll `regime task status --tasks-dir <root>/tasks` until done."""
    deadline = time.time() + timeout
    last = {}
    while time.time() < deadline:
        p = _run(["conda", "run", "-n", "regime-driver", "regime",
                  "task", "status", task_id, "--tasks-dir", str(root / "tasks"),
                  "--json"], timeout=30.0)
        last = _json(p.stdout) or {}
        status = last.get("status")
        if status not in ("running", "starting", None):
            return last
        time.sleep(15)
    print(f"  [wait] {task_id} not finished within {timeout:.0f}s", flush=True)
    return last or None


def _locate_in_container(name: str) -> list[str]:
    """Find a file under /root/work (worker cwd); sessions write into /root/work/code."""
    p = _run(["sg", "docker", "-c",
              f"docker exec {CONTAINER} find /root/work -maxdepth 3 "
              f"\\( -name {name} \\) -print 2>/dev/null"],
             timeout=60.0)
    paths = [ln.strip() for ln in (p.stdout or "").splitlines() if ln.strip()]
    # prefer the session workspace (/code) over the root
    paths.sort(key=lambda x: (0 if "/code/" in x else 1))
    return paths


def collect_artifacts(root: Path, task: QualityTask) -> Path | None:
    """docker cp the produced files (module + test + extra) into root/<task.id>/."""
    dest = root / "artifacts" / task.id
    dest.mkdir(parents=True, exist_ok=True)
    names = (task.module, task.test_file) + tuple(task.extra_files or ())
    found_any = False
    for name in names:
        paths = _locate_in_container(name)
        if not paths:
            print(f"  [cp] {name}: not found in worker", flush=True)
            continue
        for src in paths:
            p = _run(["sg", "docker", "-c",
                      f"docker cp {CONTAINER}:{src} {dest / name}"],
                     timeout=60.0)
            if p.returncode == 0:
                found_any = True
                break
            print(f"  [cp] {src}: rc={p.returncode}", flush=True)
    if not found_any:
        listing = _run(["sg", "docker", "-c",
                        f"docker exec {CONTAINER} ls /root/work/code"],
                       timeout=30.0)
        print(f"  [cp] none found; worker /root/work/code: "
              f"{listing.stdout.strip()[:300]}", flush=True)
        return None
    return dest


def host_pytest(dest: Path) -> dict:
    """Run pytest on the host for the collected artifacts."""
    if dest is None:
        return {"verifiable": False, "reason": "artifacts missing"}
    p = _run(HOST_PYTEST + ["-q", str(dest)], timeout=180.0)
    text = (p.stdout or "") + (p.stderr or "")
    passed = failed = errors = 0
    for line in text.splitlines():
        if " passed" in line or line.startswith("passed"):
            parts = line.replace(",", " ").split()
            for i, w in enumerate(parts):
                if w in ("passed", "passed!"):
                    try: passed = int(parts[i - 1])
                    except ValueError: pass
                if w == "failed":
                    try: failed = int(parts[i - 1])
                    except ValueError: pass
                if w == "error":
                    try: errors = int(parts[i - 1])
                    except ValueError: pass
    return {"verifiable": True, "rc": p.returncode,
            "passed": passed, "failed": failed, "errors": errors,
            "snippet": text[-400:]}


def _ledger_lines(ledger: Path) -> int:
    if not ledger.exists():
        return 0
    return sum(1 for _ in ledger.open(encoding="utf-8"))


def audit_ledger(root: Path, task: QualityTask, start_line: int) -> dict:
    """Count reviewer/gate events appended after `start_line` (append-only ledger)."""
    ledger = root / "events.jsonl"
    verdicts = advances = gate_exhausted = reworks = 0
    if not ledger.exists():
        return {"verdicts": 0, "advances": 0, "gate_exhausted": 0, "reworks": 0}
    with ledger.open(encoding="utf-8") as fh:
        for i, line in enumerate(fh):
            if i < start_line or not line.strip():
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            ev = d.get("event")
            if ev == "reviewer_verdict":
                verdicts += 1
                if (d.get("detail") or "").find("rework") >= 0 or d.get("action") == "rework":
                    reworks += 1
            elif ev == "advance":
                advances += 1
                frm, to = d.get("from"), d.get("to")
                if frm and to and frm == "implement" and to == "design":
                    reworks += 1
            elif isinstance(ev, str) and "gate" in ev.lower():
                gate_exhausted += 1
    return {"verdicts": verdicts, "advances": advances,
            "gate_exhausted": gate_exhausted, "reworks": reworks}


def run_one(root: Path, task: QualityTask, deadline: int,
            start_line: int) -> dict:
    print(f"== task {task.id}: {task.module} / {task.test_file} ==", flush=True)
    t0 = time.time()
    seed_task_files(root, task)
    task_id = submit_drive(root, task, deadline)
    if not task_id:
        return {"id": task.id, "submit": "failed", "elapsed_sec": round(time.time() - t0, 1),
                "covers": list(task.covers)}
    rec = wait_task(root, task_id, timeout=deadline + 120)
    elapsed = round(time.time() - t0, 1)
    summary = (rec or {}).get("summary") or {}
    outcome = summary.get("outcome") or (rec or {}).get("outcome")
    detail = summary.get("detail") or (rec or {}).get("detail")
    dest = collect_artifacts(root, task)
    py = host_pytest(dest)
    audit = audit_ledger(root, task, start_line)
    result = {
        "id": task.id,
        "task_id": task_id,
        "elapsed_sec": elapsed,
        "outcome": outcome,
        "detail": detail,
        "host_pytest": py,
        "reviewer": audit,
        "covers": list(task.covers),
        "flow": task.flow,
    }
    print(f"  -> outcome={outcome} elapsed={elapsed}s pytest={py} audit={audit}", flush=True)
    return result


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=0.0)
    ap.add_argument("--minutes", type=float, default=0.0)
    ap.add_argument("--root", type=Path, default=Path("/tmp/quality-run"))
    ap.add_argument("--deadline", type=int, default=900,
                    help="per-task drive deadline (sec)")
    ap.add_argument("--tasks", type=str, default="",
                    help="comma list of task ids to run (default: all)")
    ap.add_argument("--sample-sec", type=float, default=60.0)
    ap.add_argument("--clean-sessions", action="store_true",
                    help="run `regime sessions --clean` before each task so the "
                         "worker never degrades under session accumulation")
    args = ap.parse_args()

    root = args.root
    root.mkdir(parents=True, exist_ok=True)

    def clean_sessions() -> None:
        if not args.clean_sessions:
            return
        p = _run(["conda", "run", "-n", "regime-driver", "regime", "sessions",
                  "--clean", "--base", BASE, "--perm", "clean", "--json"],
                 timeout=120.0)
        print(f"  [clean] sessions rc={p.returncode}", flush=True)

    selected = [t for t in TASKS if not args.tasks or t.id in
                [s.strip() for s in args.tasks.split(",")]]
    # duration: run at least one task; if --minutes/--hours given, keep
    # cycling the suite until the budget is exhausted.
    budget = (args.minutes if args.minutes > 0 else args.hours * 60.0) * 60.0
    start = time.time()

    results = []
    i = 0
    while True:
        task = selected[i % len(selected)]
        clean_sessions()
        start_line = _ledger_lines(root / "events.jsonl")
        res = run_one(root, task, args.deadline, start_line)
        results.append(res)
        i += 1
        if budget > 0 and time.time() - start >= budget:
            break
        if budget == 0 and i >= len(selected):
            break

    report = {"elapsed_sec": round(time.time() - start, 1),
              "tasks_attempted": len(results),
              "results": results,
              "capability_coverage": _capability_coverage(results)}
    summary_path = root / "quality-report.json"
    summary_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    print(f"[quality] DONE {report['elapsed_sec']}s -> {summary_path}", flush=True)

    # human summary
    for r in results:
        py = r.get("host_pytest", {})
        outcome = r.get("outcome") or r.get("submit") or "unknown"
        print(f"{r['id']:16s} outcome={outcome:10s} "
              f"pytest={py.get('passed')}passed/{py.get('failed')}failed "
              f"verdicts={r.get('reviewer', {}).get('verdicts')} "
              f"elapsed={r.get('elapsed_sec')}s", flush=True)

    # capability-coverage summary (WORK_PLAN8): which designed capabilities were
    # exercised by which tasks, and which were not triggered at all.
    print("\n== capability coverage ==", flush=True)
    cov = report["capability_coverage"]
    for cap, tasks_list in cov["covered"].items():
        print(f"  {cap:28s} <- {', '.join(tasks_list)}", flush=True)
    if cov["uncovered"]:
        print("  -- NOT covered (designed but never triggered):", flush=True)
        for cap in sorted(cov["uncovered"]):
            print(f"     {cap}", flush=True)


def _capability_coverage(results: list[dict]) -> dict:
    """Aggregate which designed capabilities were exercised by which tasks.

    A capability counts as covered if at least one task that DECLARES it in
    `covers` completed (the capability is exercised by the run, not just
    declared). Uncovered = declared by some task but no declaring task
    completed successfully.
    """
    covered: dict[str, list[str]] = {}
    declared: dict[str, list[str]] = {}
    for r in results:
        tid = r.get("id")
        caps = r.get("covers") or []
        ok = r.get("outcome") in ("complete", None)  # None = preflight-only info
        for cap in caps:
            declared.setdefault(cap, []).append(tid)
            if ok:
                covered.setdefault(cap, []).append(tid)
    uncovered = sorted(set(declared) - set(covered))
    return {"covered": dict(sorted(covered.items())),
            "uncovered": uncovered,
            "declared_total": len(declared),
            "covered_total": len(covered)}


if __name__ == "__main__":
    main()
