#!/usr/bin/env python3
"""Quality-gain verification harness (WORK_PLAN6 I, L2 / WORK_PLAN9 redesign).

Runs a suite of REAL complex engineering tasks (`regime drive --async`) against
the live worker and measures, per task:

  * outcome + elapsed (complete / timeout / blocked / crashed),
  * **host-side external test**: `docker cp` the task's whole workspace out of
    the worker and re-run pytest on the host (independent of the worker's own
    run) -> N passed / failed,
  * **reviewer engagement**: reviewer_verdict / advance / gate-exhausted
    events from the event ledger (evidence the review gate did real work),
  * **full per-task archive** (WORK_PLAN9): every completed task archives its
    session message snapshots, the whole workspace, the journal/events slices
    and the result JSON BEFORE any cleanup — so any past run is fully
    reviewable, and a later `--clean-sessions` can never destroy evidence.

Design rules (learned from the 2026-08-13 nightly post-mortem):

  1. **Per-task isolated workspace**: the shared `/root/work/code` is wiped
     before each task and its ENTIRE contents are collected + archived after
     each task (no shared-dir accumulation, no cross-task contamination, no
     stale-file artifact pollution from previous runs).
  2. **Archive-before-clean**: session message snapshots are taken and written
     to the archive while the sessions still exist, and only THEN are sessions
     cleaned. Cleanup never precedes or destroys the evidence it should guard.
  3. **Interruption-safe report**: `quality-report.json` is rewritten after
     EVERY completed task (append results incrementally), not only when the
     budget is exhausted — an interrupted run never loses aggregate results.
  4. **Reasoning-aware supervision**: the suite now exercises complex tasks
     that legitimately deep-reason for minutes; the watchdog fix (reasoning
     tokens count as liveness) is what makes these tasks safe to run.

Usage:
    python ops/quality_run.py --minutes 10 [--tasks shop_inventory,kv_cluster]
    python ops/quality_run.py --hours 2 --root /tmp/quality-run
    python ops/quality_run.py --hours 2 --root /tmp/quality-run --archive tasks_docs/nightly_run_archive/<stamp>
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
WORK_ROOT = "/root/work"
WORK_CODE = f"{WORK_ROOT}/code"
HOST_PYTEST = ["conda", "run", "-n", "regime-driver", "python", "-m", "pytest"]
# per-task drive deadline = minutes_est converted to seconds + headroom, capped
# so a truly stuck task still terminates (bounded by the run's --deadline too).
_MIN_DEADLINE = 900          # 15 min floor (complex tasks)
_MAX_DEADLINE = 2700         # 45 min cap


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


def _docker(cmd: str, timeout=60.0):
    """Run a docker command via the `sg docker -c` wrapper (host group shim)."""
    return _run(["sg", "docker", "-c", cmd], timeout=timeout)


def _deadline_for(task: QualityTask, override: int | None) -> int:
    if override is not None:
        return max(_MIN_DEADLINE, min(override, _MAX_DEADLINE))
    est = task.minutes_est or 15
    return max(_MIN_DEADLINE, min(est * 60 + 300, _MAX_DEADLINE))


# --------------------------------------------------------------------------- #
# workspace: per-task isolation inside the worker container
# --------------------------------------------------------------------------- #

def wipe_workspace() -> bool:
    """Wipe the shared code dir BEFORE a task so no previous-task file lingers.

    Returns True on success. A failed wipe (e.g. container mid-restart) must
    fail the run rather than let a task start on a contaminated workspace.
    """
    p = _docker(f"docker exec {CONTAINER} bash -c 'find {WORK_CODE} -mindepth 1 -delete 2>/dev/null'")
    if p.returncode != 0:
        print(f"  [wipe] rc={p.returncode}: {p.stderr[:200]}", flush=True)
        return False
    return True


def seed_task_files(task: QualityTask) -> None:
    """Pre-seed `task.seed_files` into the worker code dir (before the task)."""
    if not task.seed_files:
        return
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        for name, content in task.seed_files.items():
            tmp = Path(td) / name
            tmp.write_text(content, encoding="utf-8")
            p = _docker(f"docker cp {tmp} {CONTAINER}:{WORK_CODE}/{name}")
            if p.returncode != 0:
                print(f"  [seed] {name}: rc={p.returncode}: {p.stderr[:200]}", flush=True)
            else:
                print(f"  [seed] {name} -> worker {WORK_CODE}/", flush=True)


def collect_workspace(dest: Path) -> Path | None:
    """docker cp the ENTIRE task workspace out into `dest` (preferred form)."""
    dest.mkdir(parents=True, exist_ok=True)
    # docker cp of a directory requires an existing parent; copy contents:
    p = _docker(f"docker cp {CONTAINER}:{WORK_CODE} {dest}/_ws")
    if p.returncode != 0:
        # docker cp -r semantics: copy dir as child; if that failed, fall back
        # to a per-file copy of known entries.
        listing = _docker(f"docker exec {CONTAINER} ls {WORK_CODE}")
        print(f"  [cp] dir copy rc={p.returncode}: {p.stderr[:200]}", flush=True)
        print(f"  [cp] worker {WORK_CODE}: {listing.stdout.strip()[:300]}", flush=True)
        return None
    # flatten: _ws/ contains the code dir's children
    ws = dest / "_ws"
    if ws.is_dir():
        for child in ws.iterdir():
            shutil.move(str(child), str(dest / child.name))
        ws.rmdir()
    return dest


# --------------------------------------------------------------------------- #
# session message snapshot (archive-before-clean)
# --------------------------------------------------------------------------- #

def snapshot_sessions(dest: Path) -> list[str]:
    """Dump ALL worker session message histories into `dest/sessions/*.jsonl`.

    Runs while the sessions still exist (before any cleanup). Returns the list
    of session ids snapshotted. Each line: one Message rendered as JSON.
    """
    sessions_dir = dest / "sessions"
    sessions_dir.mkdir(parents=True, exist_ok=True)
    from regime_driver.infra.opencode import OpenCodeClient
    client = OpenCodeClient(base_url=BASE)
    try:
        sids = [s.get("id") for s in client.list_sessions() if s.get("id")]
    except Exception as exc:  # noqa: BLE001
        print(f"  [snapshot] list sessions failed: {exc}", flush=True)
        return []
    snapshotted: list[str] = []
    for sid in sids:
        try:
            msgs = client.read_messages(sid)
        except Exception as exc:  # noqa: BLE001
            print(f"  [snapshot] {sid} read failed: {exc}", flush=True)
            continue
        out = sessions_dir / f"{sid}.jsonl"
        with out.open("w", encoding="utf-8") as fh:
            for m in msgs:
                fh.write(json.dumps({
                    "session_id": sid,
                    "id": m.id,
                    "role": m.role,
                    "text": m.text,
                    "reply": m.reply,
                    "error": m.error,
                    "completed": m.completed,
                    "finish": m.finish,
                    "ts": m.ts,
                }, ensure_ascii=False) + "\n")
        snapshotted.append(sid)
        print(f"  [snapshot] {sid}: {len(msgs)} messages", flush=True)
    return snapshotted


# --------------------------------------------------------------------------- #
# drive submission / wait / audit
# --------------------------------------------------------------------------- #

def submit_drive(root: Path, task: QualityTask, deadline: int) -> str | None:
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


def _ledger_lines(ledger: Path) -> int:
    if not ledger.exists():
        return 0
    with ledger.open(encoding="utf-8") as fh:
        return sum(1 for _ in fh)


def audit_ledger(root: Path, start_line: int) -> dict:
    """Count reviewer/gate events appended after `start_line` (append-only ledger)."""
    ledger = root / "events.jsonl"
    verdicts = advances = gate_exhausted = reworks = inquiries = 0
    if not ledger.exists():
        return {"verdicts": 0, "advances": 0, "gate_exhausted": 0,
                "reworks": 0, "inquiries": 0}
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
            elif ev == "reviewer_inquiry":
                inquiries += 1
            elif isinstance(ev, str) and "gate" in ev.lower():
                gate_exhausted += 1
    return {"verdicts": verdicts, "advances": advances,
            "gate_exhausted": gate_exhausted, "reworks": reworks,
            "inquiries": inquiries}


def slice_appendonly(path: Path, start_line: int, dest: Path) -> int:
    """Copy the lines appended since `start_line` of an append-only file to `dest`."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    if not path.exists():
        return 0
    with path.open(encoding="utf-8") as fh, dest.open("w", encoding="utf-8") as out:
        for i, line in enumerate(fh):
            if i >= start_line and line.strip():
                out.write(line)
                written += 1
    return written


def host_pytest(dest: Path) -> dict:
    """Run pytest on the host for the collected task workspace."""
    if dest is None:
        return {"verifiable": False, "reason": "workspace missing"}
    p = _run(HOST_PYTEST + ["-q", str(dest)], timeout=300.0)
    text = (p.stdout or "") + (p.stderr or "")
    import re as _re
    passed = failed = errors = 0
    for line in text.splitlines():
        m = _re.search(r"(\d+)\s+passed", line)
        if m:
            passed = int(m.group(1))
        m = _re.search(r"(\d+)\s+failed", line)
        if m:
            failed = int(m.group(1))
        m = _re.search(r"(\d+)\s+error", line)
        if m:
            errors = int(m.group(1))
    return {"verifiable": True, "rc": p.returncode,
            "passed": passed, "failed": failed, "errors": errors,
            "snippet": text[-500:]}


# --------------------------------------------------------------------------- #
# per-task run + archive
# --------------------------------------------------------------------------- #

def run_one(root: Path, archive: Path | None, task: QualityTask, deadline: int,
            start_line: int, journal_start: int) -> dict:
    print(f"== task {task.id}: est {task.minutes_est}min, deadline {deadline}s ==",
          flush=True)
    t0 = time.time()
    task_dir = archive / task.id if archive else root / "tasks" / task.id
    # W1: rebuild the per-task archive dir so a re-run of the same task id does
    # not mix stale host-side files (from a previous night) into this run's
    # collection / host_pytest.
    if task_dir.exists():
        shutil.rmtree(task_dir)
    task_dir.mkdir(parents=True, exist_ok=True)

    if not wipe_workspace():
        res = {"id": task.id, "submit": "failed: workspace wipe",
               "elapsed_sec": round(time.time() - t0, 1),
               "covers": list(task.covers)}
        _write_task_result(task_dir, res)
        return res
    seed_task_files(task)
    task_id = submit_drive(root, task, deadline)
    if not task_id:
        res = {"id": task.id, "submit": "failed",
               "elapsed_sec": round(time.time() - t0, 1),
               "covers": list(task.covers)}
        _write_task_result(task_dir, res)
        return res

    rec = wait_task(root, task_id, timeout=deadline + 120)
    elapsed = round(time.time() - t0, 1)
    summary = (rec or {}).get("summary") or {}
    outcome = summary.get("outcome") or (rec or {}).get("outcome") or "unknown"
    detail = summary.get("detail") or (rec or {}).get("detail")

    # archive BEFORE any cleanup: message snapshots + workspace + slices
    snapshotted = snapshot_sessions(task_dir)
    dest = collect_workspace(task_dir)
    py = host_pytest(dest)
    audit = audit_ledger(root, start_line)
    jstart = journal_start
    n_journal = slice_appendonly(root / "journal.jsonl", jstart,
                                 task_dir / "journal-slice.jsonl")
    n_ledger = slice_appendonly(root / "events.jsonl", start_line,
                                task_dir / "events-slice.jsonl")

    res = {
        "id": task.id,
        "task_id": task_id,
        "elapsed_sec": elapsed,
        "outcome": outcome,
        "detail": detail,
        "host_pytest": py,
        "reviewer": audit,
        "covers": list(task.covers),
        "flow": task.flow,
        "archive": str(task_dir),
        "sessions_snapshotted": snapshotted,
        "slices": {"journal": n_journal, "events": n_ledger},
    }
    _write_task_result(task_dir, res)
    print(f"  -> outcome={outcome} elapsed={elapsed}s pytest={py} "
          f"audit={audit} snap={len(snapshotted)}", flush=True)
    return res


def _write_task_result(task_dir: Path, res: dict) -> None:
    (task_dir / "result.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _capability_coverage(results: list[dict]) -> dict:
    covered: dict[str, list[str]] = {}
    declared: dict[str, list[str]] = {}
    for r in results:
        tid = r.get("id")
        caps = r.get("covers") or []
        ok = r.get("outcome") == "complete"
        for cap in caps:
            declared.setdefault(cap, []).append(tid)
            if ok:
                covered.setdefault(cap, []).append(tid)
    uncovered = sorted(set(declared) - set(covered))
    return {"covered": dict(sorted(covered.items())),
            "uncovered": uncovered,
            "declared_total": len(declared),
            "covered_total": len(covered)}


def write_report(root: Path, results: list[dict], start: float) -> None:
    report = {"elapsed_sec": round(time.time() - start, 1),
              "tasks_attempted": len(results),
              "results": results,
              "capability_coverage": _capability_coverage(results)}
    summary_path = root / "quality-report.json"
    summary_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
    print(f"[quality] incremental report -> {summary_path} "
          f"({len(results)} tasks)", flush=True)


# --------------------------------------------------------------------------- #
# main loop
# --------------------------------------------------------------------------- #

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=0.0)
    ap.add_argument("--minutes", type=float, default=0.0)
    ap.add_argument("--root", type=Path, default=Path("/tmp/quality-run"))
    ap.add_argument("--deadline", type=int, default=None,
                    help="per-task drive deadline override (sec)")
    ap.add_argument("--tasks", type=str, default="",
                    help="comma list of task ids to run (default: all)")
    ap.add_argument("--sample-sec", type=float, default=60.0)
    ap.add_argument("--clean-sessions", action="store_true",
                    help="clean worker sessions AFTER each task is archived")
    ap.add_argument("--archive", type=Path, default=None,
                    help="archive directory for full per-task artifacts "
                         "(default: <root>/archive)")
    args = ap.parse_args()

    root = args.root
    root.mkdir(parents=True, exist_ok=True)
    archive = args.archive or (root / "archive")
    archive.mkdir(parents=True, exist_ok=True)

    def clean_sessions() -> None:
        if not args.clean_sessions:
            return
        p = _run(["conda", "run", "-n", "regime-driver", "regime", "sessions",
                  "--clean", "--base", BASE, "--perm", "clean", "--json"],
                 timeout=120.0)
        print(f"  [clean] sessions rc={p.returncode}", flush=True)

    selected = [t for t in TASKS if not args.tasks or t.id in
                [s.strip() for s in args.tasks.split(",")]]
    budget = (args.minutes if args.minutes > 0 else args.hours * 60.0) * 60.0
    start = time.time()

    results: list[dict] = []
    i = 0
    while True:
        task = selected[i % len(selected)]
        deadline = _deadline_for(task, args.deadline)
        start_line = _ledger_lines(root / "events.jsonl")
        journal_start = _ledger_lines(root / "journal.jsonl")
        res = run_one(root, archive, task, deadline, start_line, journal_start)
        results.append(res)
        # interruption-safe: rewrite the aggregate after EVERY task
        write_report(root, results, start)
        # archive-before-clean: sessions already snapshotted inside run_one
        clean_sessions()
        i += 1
        if budget > 0 and time.time() - start >= budget:
            break
        if budget == 0 and i >= len(selected):
            break

    # human summary
    print("\n== results ==", flush=True)
    for r in results:
        py = r.get("host_pytest", {})
        outcome = r.get("outcome") or r.get("submit") or "unknown"
        print(f"{r['id']:16s} outcome={outcome:10s} "
              f"pytest={py.get('passed')}passed/{py.get('failed')}failed "
              f"verdicts={r.get('reviewer', {}).get('verdicts')} "
              f"elapsed={r.get('elapsed_sec')}s archive={r.get('archive')}",
              flush=True)

    print("\n== capability coverage ==", flush=True)
    cov = _capability_coverage(results)
    for cap, tasks_list in cov["covered"].items():
        print(f"  {cap:28s} <- {', '.join(tasks_list)}", flush=True)
    if cov["uncovered"]:
        print("  -- NOT covered (designed but never triggered):", flush=True)
        for cap in sorted(cov["uncovered"]):
            print(f"     {cap}", flush=True)
    print(f"\n[quality] archive: {archive}", flush=True)


if __name__ == "__main__":
    main()
