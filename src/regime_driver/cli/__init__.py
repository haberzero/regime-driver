"""regime-driver CLI (typer + rich)."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table
from rich.text import Text

from .. import __version__
from ..core.contract import gate_reviewer_verdict, parse_reviewer_verdict
from ..core.models import Outcome
from ..core.state_machine import StateMachineError
from ..infra.config import load_settings
from ..infra.ledger import Ledger
from ..infra.opencode import OpenCodeClient
from ..infra.regime_loader import load_regime
from ..infra.settings import Settings
from ..app.statechart_driver import StatechartDriver

console = Console()

app = typer.Typer(
    name="regime",
    help="L1 institutional-process robot: drive a clean opencode worker.",
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        console.print(f"[bold]regime-driver[/bold] [cyan]{__version__}[/cyan]")
        raise typer.Exit()


@app.callback()
def main(
    version: bool = typer.Option(False, "--version", callback=_version_callback),
) -> None:
    """regime-driver CLI."""


def _fail(message: str, markup: bool = False) -> None:
    console.print(Text("✗ ", style="bold red") + (Text(message) if not markup else Text.from_markup(message)))
    raise typer.Exit(1)


def _ok(message: str, markup: bool = False) -> None:
    console.print(Text("✓ ", style="bold green") + (Text(message) if not markup else Text.from_markup(message)))


def _emit_json(data) -> None:
    """Print machine-readable JSON to raw stdout (the CLI contract's --json surface).

    Must bypass rich's console (which word-wraps long lines and would corrupt
    large JSON). Machine consumers parse this verbatim.
    """
    sys.stdout.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def _effective_held(perm: str) -> "PermissionLevel":
    """The effective held permission: capped by the configured ceiling.

    The ceiling comes from the operator's environment (REGIME_PERMISSION_CEILING,
    matching the settings env convention), so a self-declared ``--perm`` can
    never raise above it — only lower.
    """
    import os

    from ..infra.permission import PermissionLevel, clamp

    ceiling_value = os.environ.get("REGIME_PERMISSION_CEILING", "clean")
    ceiling = PermissionLevel(ceiling_value)
    return clamp(PermissionLevel(perm), ceiling)


def _gate(perm: str, argv: list[str]) -> None:
    """Enforce the permission gate before a (potentially) write command.

    The effective held level is **capped by the configured ceiling**
    (Settings.permission_ceiling, from config/env), never by the self-declared
    ``--perm``. So an operator cannot self-elevate: passing ``--perm clean`` is
    inert if the ceiling is lower. ``--perm`` may only lower the held level.
    """
    from ..infra.permission import PermissionDenied, classify, require

    try:
        require(_effective_held(perm), classify(argv))
    except (PermissionDenied, ValueError) as exc:
        _fail(str(exc))


def _submit_job(job_type: str, argv: list[str], *, ledger: str | None = None,
                title: str = "", json_out: bool = False) -> None:
    """Submit a background async job and print its handle."""
    from ..infra.jobs import JobRegistry, public_record

    record = JobRegistry().create(job_type, argv, ledger=ledger, title=title)
    if json_out:
        _emit_json({"submitted": True, "job": public_record(record)})
        return
    _ok(f"job [bold]{record['id']}[/bold] submitted "
        f"(pid={record['pid']}, type={job_type})", markup=True)
    _ok(f"status: regime job status {record['id']}", markup=False)


# ---------------------------------------------------------------------------
# run
# ---------------------------------------------------------------------------
@app.command("run")
def run(
    context: str = typer.Argument(..., help="task context injected into developer nodes"),
    base: str = typer.Option(None, "--base", help="worker opencode server URL"),
    config: Optional[Path] = typer.Option(None, "--config", help="config file (JSON/TOML)"),
    regime: Optional[Path] = typer.Option(None, "--regime", help="path to regime.json"),
    ledger: Optional[Path] = typer.Option(None, "--ledger", help="JSONL ledger path"),
    deadline: int = typer.Option(None, "--deadline", help="per-segment deadline (sec)"),
    title: str = typer.Option("regime-driver", "--title"),
    skills_dir: Optional[Path] = typer.Option(
        None, "--skills-dir", help="path to workflow-regime skills dir"
    ),
    task_control_dir: Optional[Path] = typer.Option(
        None, "--task-control-dir", help="project dir for task-control docs"
    ),
    json_out: bool = typer.Option(False, "--json", help="machine-readable JSON result"),
    async_run: bool = typer.Option(
        False, "--async", help="submit as a background job and return a handle immediately"
    ),
    perm: str = typer.Option("run", "--perm", help="held permission level "
                             "(read|interact|run|clean); gates write ops"),
    no_preflight: bool = typer.Option(
        False, "--no-preflight", help="SKIP the mandatory offline preflight trial (not recommended)"
    ),
    reporter: Optional[Path] = typer.Option(
        None, "--reporter", help="append-only report journal path (report bus)"
    ),
) -> None:
    """Run a task through the regime flow on a developer session."""
    _gate(perm, ["run", context])
    settings = load_settings(
        config_file=config,
        overrides={
            "base_url": base,
            "regime_path": str(regime) if regime else None,
            "ledger_path": str(ledger) if ledger else None,
            "default_deadline_sec": deadline,
            "skills_dir": str(skills_dir) if skills_dir else None,
            "task_control_dir": str(task_control_dir) if task_control_dir else None,
        },
    )
    if async_run:
        # preflight runs inside the background subprocess (its own default is ON),
        # so async stays non-blocking; only forward an explicit opt-out.
        job_argv = [
            "run", context,
            *(["--base", base] if base else []),
            *(["--config", str(config)] if config else []),
            *(["--regime", str(regime)] if regime else []),
            *(["--ledger", str(ledger)] if ledger else []),
            *(["--deadline", str(deadline)] if deadline is not None else []),
            *(["--title", title] if title != "regime-driver" else []),
            *(["--skills-dir", str(skills_dir)] if skills_dir else []),
            *(["--task-control-dir", str(task_control_dir)] if task_control_dir else []),
            *(["--no-preflight"] if no_preflight else []),
            *(["--reporter", str(reporter)] if reporter else []),
        ]
        _submit_job("run", job_argv, ledger=str(ledger) if ledger else None,
                    title=title, json_out=json_out)
        return
    # mandatory preflight (offline trial) before touching a real worker/session
    if not no_preflight:
        from ..app.preflight import preflight
        from ..core.state_machine import StateMachineError

        try:
            sm = load_regime(regime)
        except (StateMachineError, FileNotFoundError) as exc:
            _fail(f"error loading regime: {exc}")
        res = preflight(sm, timeout_sec=30.0)
        if json_out:
            _emit_json({"preflight": res, "started": False})
        if not res["ok"]:
            _fail(f"preflight FAILED: outcome={res['outcome']} detail={res['detail']}")
        else:
            _ok(f"preflight PASSED (offline outcome={res['outcome']})", markup=False)
    _run(settings, context, title, json_out=json_out, reporter=reporter)


def _run(settings: Settings, context: str, title: str, json_out: bool = False,
         reporter: Optional[Path] = None) -> None:
    try:
        sm = load_regime(settings.regime_path)
    except (StateMachineError, FileNotFoundError) as exc:
        _fail(f"error loading regime: {exc}")

    from ..app.reporter import Reporter

    client = OpenCodeClient(settings.base_url, model=settings.model,
                            timeout=settings.request_timeout)
    ledger = Ledger(settings.ledger_path) if settings.ledger_path else None
    rep = Reporter(journal_path=reporter) if reporter else None
    driver = StatechartDriver(settings, sm, client, ledger, reporter=rep)
    try:
        _run_impl(driver, ledger, sm, context, title, json_out)
    finally:
        if rep:
            rep.close()


def _run_impl(driver, ledger, sm, context, title, json_out) -> None:

    # run the driver on a background thread so we can render live progress
    import threading
    result = {}
    def _go():
        try:
            result["res"] = driver.run(context, title)
        finally:
            if ledger:
                ledger.close()
    t = threading.Thread(target=_go, daemon=True)
    t0 = time.time()
    t.start()
    try:
        from rich.live import Live
        from rich.table import Table
        with Live(console=console, refresh_per_second=4) as live:
            while t.is_alive():
                table = Table(title=f"flow {sm.flow_name} · {time.time()-t0:.0f}s",
                              show_header=False)
                table.add_column(justify="right")
                table.add_column()
                wf = getattr(driver, "workflow", None)
                node = getattr(wf, "_node", None) or "?"
                phase = getattr(wf, "_phase", None) or "?"
                state = getattr(wf, "_state", None) or "?"
                table.add_row("node", node)
                table.add_row("phase", phase)
                table.add_row("state", state)
                live.update(table)
                time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    t.join(timeout=5)
    if "res" not in result:
        _fail("run did not complete")
    outcome, end_node, detail = result["res"]
    if json_out:
        _emit_json({"outcome": outcome.value, "end": end_node, "detail": detail,
                    "elapsed_sec": round(time.time()-t0, 1)})
        if outcome != Outcome.COMPLETE:
            raise typer.Exit(1)
        return
    if outcome == Outcome.COMPLETE:
        _ok(f"flow completed at node [bold]{end_node}[/bold] "
            f"in {time.time()-t0:.0f}s", markup=True)
    else:
        _fail(f"flow {outcome.value} at node [bold]{end_node}[/bold]"
              + (f": {detail}" if detail else ""), markup=True)


# ---------------------------------------------------------------------------
# run-many
# ---------------------------------------------------------------------------
@app.command("run-many")
def run_many(
    contexts: list[str] = typer.Argument(..., help="one or more task contexts (one workflow each)"),
    base: str = typer.Option(None, "--base", help="worker opencode server URL"),
    config: Optional[Path] = typer.Option(None, "--config", help="config file (JSON/TOML)"),
    regime: Optional[Path] = typer.Option(None, "--regime", help="path to regime.json"),
    ledger: Optional[Path] = typer.Option(None, "--ledger", help="JSONL ledger path"),
    deadline: int = typer.Option(None, "--deadline", help="per-segment deadline (sec)"),
    skills_dir: Optional[Path] = typer.Option(
        None, "--skills-dir", help="path to workflow-regime skills dir"),
    json_out: bool = typer.Option(False, "--json", help="machine-readable JSON result"),
    async_run: bool = typer.Option(
        False, "--async", help="submit as a background job and return a handle immediately"
    ),
    perm: str = typer.Option("run", "--perm", help="held permission level "
                             "(read|interact|run|clean); gates write ops"),
    no_preflight: bool = typer.Option(
        False, "--no-preflight", help="SKIP the mandatory offline preflight trial (not recommended)"
    ),
    reporter: Optional[Path] = typer.Option(
        None, "--reporter", help="append-only report journal path (report bus)"
    ),
) -> None:
    """Run several tasks as concurrent workflows on one worker."""
    _gate(perm, ["run-many", *contexts])
    from ..app.statechart_cluster import StatechartCluster
    from ..app.reporter import Reporter

    settings = load_settings(
        config_file=config,
        overrides={
            "base_url": base,
            "regime_path": str(regime) if regime else None,
            "ledger_path": str(ledger) if ledger else None,
            "default_deadline_sec": deadline,
            "skills_dir": str(skills_dir) if skills_dir else None,
        },
    )
    if async_run:
        _submit_job("run-many", [
            "run-many", *contexts,
            *(["--base", base] if base else []),
            *(["--config", str(config)] if config else []),
            *(["--regime", str(regime)] if regime else []),
            *(["--ledger", str(ledger)] if ledger else []),
            *(["--deadline", str(deadline)] if deadline is not None else []),
            *(["--skills-dir", str(skills_dir)] if skills_dir else []),
            *(["--no-preflight"] if no_preflight else []),
            *(["--reporter", str(reporter)] if reporter else []),
        ], ledger=str(ledger) if ledger else None, title=f"run-many×{len(contexts)}",
            json_out=json_out)
        return
    try:
        sm = load_regime(settings.regime_path)
    except (StateMachineError, FileNotFoundError) as exc:
        _fail(f"error loading regime: {exc}")

    if not no_preflight:
        from ..app.preflight import preflight

        res = preflight(sm, timeout_sec=30.0)
        if not res["ok"]:
            _fail(f"preflight FAILED: outcome={res['outcome']} detail={res['detail']}")
        _ok(f"preflight PASSED (offline outcome={res['outcome']})", markup=False)

    client = OpenCodeClient(settings.base_url, model=settings.model,
                            timeout=settings.request_timeout)
    rep = Reporter(journal_path=reporter) if reporter else None
    cluster = StatechartCluster(client, reporter=rep)
    for i, ctx in enumerate(contexts):
        cluster.add_workflow(f"w{i+1}", settings, sm)
    t0 = time.time()
    # run the cluster in a background thread so we can render live progress
    import threading
    result = {}
    def _go():
        try:
            result["res"] = cluster.run_all(
                {f"w{i+1}": ctx for i, ctx in enumerate(contexts)},
                timeout_sec=settings.request_timeout)
        finally:
            cluster.stop()
    t = threading.Thread(target=_go, daemon=True)
    t.start()
    try:
        from rich.live import Live
        from rich.table import Table
        with Live(console=console, refresh_per_second=4) as live:
            while t.is_alive():
                table = Table(title=f"run-many · {time.time()-t0:.0f}s",
                              show_header=False)
                table.add_column(justify="right")
                table.add_column()
                bb = cluster.runtime.bus.blackboard
                rows = []
                for wid in sorted(getattr(cluster, "workflows", {}) or {}):
                    node = bb.get(f"{wid}.node") or "?"
                    state = bb.get(f"{wid}.state") or "?"
                    rows.append((wid, f"{node} ({state})"))
                if not rows:
                    rows.append(("(no workflows yet)", ""))
                for k, v in rows:
                    table.add_row(k, v)
                live.update(table)
                time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    t.join(timeout=5)
    if "res" not in result:
        _fail("run-many did not complete")
    results = result["res"]
    try:
        if json_out:
            _emit_json({"elapsed_sec": round(time.time()-t0, 1), "results": {
                wid: {"outcome": r[0].value, "end": r[1], "detail": r[2]}
                for wid, r in results.items()}})
            if any(r[0] != Outcome.COMPLETE for r in results.values()):
                raise typer.Exit(1)
            return
        print(f"\n=== run-many 结果 ({time.time()-t0:.0f}s) ===")
        for wid, r in results.items():
            outcome, end, detail = r
            mark = "✓" if outcome == Outcome.COMPLETE else "✗"
            console.print(f"  {mark} {wid}: {outcome.value} @ {end}"
                          + (f" ({detail})" if detail else ""))
        bad = [wid for wid, r in results.items() if r[0] != Outcome.COMPLETE]
        if bad:
            _fail(f"{len(bad)} workflow(s) not complete: {', '.join(bad)}", markup=False)
        _ok(f"all {len(results)} workflows done", markup=False)
    finally:
        if rep:
            rep.close()


# ---------------------------------------------------------------------------
# preflight
# ---------------------------------------------------------------------------
@app.command("preflight")
def preflight_cmd(
    regime: Optional[Path] = typer.Option(
        None, "--regime", help="path to regime.json (default: packaged descriptor)"
    ),
    fault: str = typer.Option(
        None, "--fault", help="fault injection: stall | delay (elasticity trial)"
    ),
    json_out: bool = typer.Option(False, "--json", help="machine-readable JSON"),
) -> None:
    """Run an offline trial of the flow (MockClient) to verify it terminates cleanly.

    Catches semantic errors static checks miss (gate never advances, no terminal,
    unservable role) before a real worker/session is touched.
    """
    from ..app.preflight import preflight
    from ..core.state_machine import StateMachineError

    try:
        sm = load_regime(regime)
    except (StateMachineError, FileNotFoundError) as exc:
        _fail(f"error loading regime: {exc}")
    res = preflight(sm, fault=fault, timeout_sec=30.0)
    if json_out:
        _emit_json(res)
        if not res["ok"]:
            raise typer.Exit(1)
        return
    if res["ok"]:
        _ok(f"preflight PASSED: offline outcome={res['outcome']} @ {res['end']}", markup=False)
    else:
        _fail(f"preflight FAILED: outcome={res['outcome']} @ {res['end']} "
              f"detail={res['detail']!r}", markup=False)


# ---------------------------------------------------------------------------
# report
# ---------------------------------------------------------------------------
@app.command("report")
def report_cmd(
    journal: str = typer.Option(None, "--journal", help="path to report journal (JSONL)"),
    wf_id: str = typer.Option(None, "--wf", help="filter by workflow id"),
    history: bool = typer.Option(False, "--history", help="also print journal records"),
    limit: int = typer.Option(50, "--limit", help="max history records"),
    template: str = typer.Option(
        None, "--template",
        help="report template: milestone | blocker | period | activity"),
    since: float = typer.Option(None, "--since", help="epoch seconds; lower bound for period/activity"),
    tasks_dir: str = typer.Option(
        None, "--tasks-dir", help="supervised-task registry dir to merge into the board"),
    prune: bool = typer.Option(False, "--prune", help="prune the journal (retention)"),
    max_age: float = typer.Option(
        None, "--max-age", help="with --prune: drop records older than this many seconds"),
    max_records: int = typer.Option(
        None, "--max-records", help="with --prune: keep only this many tail records"),
    object_id: str = typer.Argument(
        None, help="single-object view: workflow/session id to focus on"),
    trace: bool = typer.Option(
        False, "--trace", help="print the per-object causal timeline (journal in order)"),
    json_out: bool = typer.Option(False, "--json", help="machine-readable JSON"),
) -> None:
    """Show the report bus: global rollup board + optional journal history.

    Reads a journal written by `regime run ... --reporter <path>`. Rollups are
    O(1) counters; history is the bounded append-only slice. Templates produce
    rule-based formatted reports (milestone/blocker/period/activity). This is the
    macro project-management surface for the God Dialog (WORK_PLAN4 III).
    """
    from ..app.reporter import Reporter

    rep = Reporter(journal_path=journal) if journal else Reporter()
    try:
        if journal:
            rep.load()
        if prune:
            if not journal:
                _fail("--prune requires --journal")
            removed = rep.retain(max_age_sec=max_age, max_records=max_records)
            if json_out:
                _emit_json({"pruned": removed})
            else:
                _ok(f"pruned {removed} record(s) from journal", markup=False)
            return
        focus = object_id or wf_id
        rollups = rep.rollup(wf_id=focus)
        tasks = []
        if tasks_dir:
            from ..infra.oc_tasks import load_tasks

            tasks = load_tasks(tasks_dir)
        if focus and trace:
            _report_trace(rep, focus, limit=limit, json_out=json_out)
            return
        if template:
            _report_template(rep, rollups, template, since=since, wf_id=focus,
                             limit=limit, json_out=json_out)
            return
        _report_board(rep, rollups, history, focus, limit, json_out, tasks=tasks)
    finally:
        rep.close()


def _report_board(rep, rollups, history, wf_id, limit, json_out, tasks=None) -> None:
    tasks = tasks or []
    if json_out:
        out = {"rollups": rollups}
        if tasks:
            out["tasks"] = tasks
        if history:
            out["history"] = rep.journal_slice(wf_id=wf_id, limit=limit)
        _emit_json(out)
        return
    if not rollups and not tasks:
        console.print("[dim]no report data[/dim]")
        return
    if rollups:
        table = Table(title="report bus · rollups", show_header=True)
        for col in ("wf", "outcome", "node", "phase", "entered", "done", "elapsed"):
            table.add_column(col)
        for r in rollups:
            table.add_row(str(r["wf_id"]), str(r["outcome"] or "-"),
                          str(r["current_node"] or "-"), str(r["current_phase"] or "-"),
                          str(r["nodes_entered"]), str(r["nodes_done"]),
                          f"{r['elapsed_sec'] or '-'}s")
        console.print(table)
    if tasks:
        t = Table(title="supervised tasks", show_header=True)
        for col in ("id", "status", "outcome", "goal", "deadline"):
            t.add_column(col)
        for x in tasks:
            st = x["status"]
            style = "bold yellow" if st == "running" else (
                "green" if st == "done" else "bold red")
            t.add_row(x["id"], Text(st, style=style), str(x["outcome"] or "-"),
                      str(x["goal"] or "-"), str(x["deadline"] or "-"))
        console.print(t)
    if history:
        h = rep.journal_slice(wf_id=wf_id, limit=limit)
        console.print(f"\n[bold]journal · last {len(h)} records[/bold]")
        for rec in h:
            console.print(f"  {rec['ts']:.1f} {rec['kind']} "
                          f"wf={rec['wf_id']} node={rec.get('node')} "
                          f"outcome={rec.get('outcome')}")


def _report_trace(rep, focus, limit=None, json_out=False) -> None:
    """Per-object causal timeline: journal records for an object in order."""
    recs = rep.journal_slice(wf_id=focus, limit=limit)
    if json_out:
        _emit_json({"object": focus, "trace": recs})
        return
    console.print(f"[bold]trace · {focus} · {len(recs)} records[/bold]")
    for rec in recs:
        console.print(f"  {rec['ts']:.1f} {rec['kind']} node={rec.get('node')} "
                      f"outcome={rec.get('outcome')} "
                      f"detail={rec.get('detail') or ''}")


def _report_template(rep, rollups, template, *, since=None, wf_id=None,
                     limit=None, json_out=False) -> None:
    """Rule-based formatted report templates (WORK_PLAN4 R-C)."""
    recs = rep.journal_slice(wf_id=wf_id, since=since, limit=limit)
    if template == "activity":
        out = [{"ts": r["ts"], "kind": r["kind"], "wf": r["wf_id"],
                "node": r.get("node"), "outcome": r.get("outcome"),
                "detail": r.get("detail")} for r in recs]
        if json_out:
            _emit_json({"template": "activity", "records": out})
        else:
            console.print(f"[bold]activity log · {len(out)} records[/bold]")
            for r in out:
                console.print(f"  {r['ts']:.1f} {r['kind']} wf={r['wf']} "
                              f"node={r['node']} outcome={r['outcome']}")
        return

    if template == "milestone":
        keys = {"advance", "transition", "outcome", "reviewer_verdict"}
        out = [r for r in recs if r.get("kind") in keys]
        if json_out:
            _emit_json({"template": "milestone", "records": out})
        else:
            console.print(f"[bold]milestones · {len(out)} key transitions[/bold]")
            for r in out[-limit or len(out):]:
                console.print(f"  {r['ts']:.1f} {r['kind']} wf={r['wf_id']} "
                              f"node={r.get('node')} outcome={r.get('outcome')} "
                              f"detail={r.get('detail') or ''}")
        return

    if template == "blocker":
        bad = {"failed", "blocked", "human", "error", "aborted", "timeout"}
        out = [r for r in recs
               if r.get("kind") == "outcome" and r.get("outcome") in bad]
        if json_out:
            _emit_json({"template": "blocker", "records": out})
        else:
            console.print(f"[bold]blockers · {len(out)}[/bold]")
            for r in out:
                console.print(f"  {r['ts']:.1f} wf={r['wf_id']} outcome={r['outcome']} "
                              f"detail={r.get('detail') or ''}")
        return

    if template == "period":
        # aggregate the bounded journal window into counts by kind and outcome
        by_kind: dict[str, int] = {}
        by_outcome: dict[str, int] = {}
        for r in recs:
            by_kind[r["kind"]] = by_kind.get(r["kind"], 0) + 1
            oc = r.get("outcome")
            if oc:
                by_outcome[oc] = by_outcome.get(oc, 0) + 1
        out = {"window_records": len(recs), "by_kind": by_kind,
               "by_outcome": by_outcome, "rollups": rollups}
        if json_out:
            _emit_json({"template": "period", **out})
        else:
            console.print(f"[bold]period report · {len(recs)} records in window[/bold]")
            console.print(f"  by_kind: {by_kind}")
            console.print(f"  by_outcome: {by_outcome}")
            console.print(f"  rollups: {len(rollups)}")
        return

    _fail(f"unknown template '{template}' (milestone|blocker|period|activity)", markup=False)


# ---------------------------------------------------------------------------
# supervisor (process-external watchdog; run on host with its own clock)
# ---------------------------------------------------------------------------
@app.command("supervisor")
def supervisor_cmd(
    base: str = typer.Option(Settings().base_url, "--base", help="worker URL"),
    session: str = typer.Option(None, "--session", help="session id to supervise"),
    container: str = typer.Option(None, "--container", help="docker container for L4 restart"),
    deadline: int = typer.Option(None, "--deadline", help="deadline seconds (0 = none)"),
    stall: int = typer.Option(60, "--stall", help="stall detection seconds (T2)"),
    reporter: Optional[Path] = typer.Option(
        None, "--reporter", help="report journal path (single truth)"),
    once: bool = typer.Option(
        False, "--once", help="do a single watchdog pass then exit (for tests/CI)"),
    json_out: bool = typer.Option(False, "--json", help="machine-readable JSON result"),
) -> None:
    """Process-external supervisor: T1 health, T2 stall, deadline, ladder.

    Runs on the HOST (independent clock), supervising a worker session. It
    consumes the worker SSE event_stream into the Reporter and enforces the
    correction ladder (abort/restart/fallback/human). Runs continuously until
    the deadline, a container restart, or an L5 human escalation (use --once for
    a single pass). This is the first-class replacement for the old M0 supervisor
    (DESIGN-supervision.md).
    """
    from ..app.reporter import Reporter
    from ..supervisor import Supervisor

    client = OpenCodeClient(base, model=Settings().model)
    rep = Reporter(journal_path=reporter) if reporter else Reporter(project_id="supervisor")
    sup = Supervisor(
        client, rep, container=container, stall_sec=stall,
        deadline_sec=deadline if deadline else None,
        session_id=session or None, goal="",
    )
    try:
        outcome = sup.run(once=once)
        if json_out:
            _emit_json({"outcome": outcome, "session": session})
        else:
            _ok(f"supervisor pass: outcome={outcome}", markup=False)
    finally:
        rep.close()


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------
@app.command("validate")
def validate(
    regime: Optional[Path] = typer.Option(
        None, "--regime", help="path to regime.json (default: packaged descriptor)"
    ),
    deep: bool = typer.Option(
        True, "--deep/--no-deep",
        help="run semantic deep checks (roles/skills/tools/reachability); ON by default"
    ),
    skills_dir: Optional[Path] = typer.Option(
        None, "--skills-dir", help="path to workflow-regime skills dir (for --deep skill check)"
    ),
    json_out: bool = typer.Option(False, "--json", help="machine-readable JSON"),
) -> None:
    """Validate a regime.json state machine descriptor."""
    try:
        sm = load_regime(regime)
        path = sm.flow_path()
    except (StateMachineError, FileNotFoundError) as exc:
        if json_out:
            _emit_json({"ok": False, "error": str(exc)})
            raise typer.Exit(1)
        _fail(f"INVALID: {exc}")

    flows = list(sm.regime.flows)
    dead = [name for name in flows if name != sm.flow_name]
    deep_res = None
    if deep:
        from ..core.validate import deep_validate
        from ..infra.skill_loader import load_skill

        deep_res = deep_validate(
            sm,
            load_skill=lambda name: load_skill(name, str(skills_dir) if skills_dir else None),
        )

    if json_out:
        out = {
            "ok": True, "flow": sm.flow_name, "nodes": len(sm.flow.nodes),
            "path": path, "flows": flows, "unreachable": dead,
        }
        if deep_res is not None:
            out["deep"] = deep_res.to_dict
            out["ok"] = out["ok"] and deep_res.ok
        _emit_json(out)
        if not out["ok"]:
            raise typer.Exit(1)
        return

    table = Table(title="regime descriptor", show_header=False)
    table.add_column("key", style="bold cyan")
    table.add_column("value")
    table.add_row("flow", sm.flow_name)
    table.add_row("nodes", str(len(sm.flow.nodes)))
    table.add_row("path length", str(len(path)))
    table.add_row("path", " → ".join(path))
    console.print(table)

    # report flows that exist but are not the entry (potentially dead config)
    if len(flows) > 1 and dead:
        console.print("[dim]warning: flows not reachable from entry "
                      f"(entry='{sm.flow_name}'): {', '.join(dead)}[/dim]")
    if deep_res is not None:
        console.print("\n[bold]--deep semantic checks[/bold]")
        if not deep_res.errors and not deep_res.warnings:
            console.print("  ✓ all deep checks passed")
        for e in deep_res.errors:
            console.print(f"  [bold red]✗ {e}[/bold red]")
        for w in deep_res.warnings:
            console.print(f"  [dim]⚠ {w}[/dim]")
        if not deep_res.ok:
            _fail(f"{len(deep_res.errors)} deep error(s) found", markup=False)
    _ok("valid regime descriptor")


# ---------------------------------------------------------------------------
# gate
# ---------------------------------------------------------------------------
@app.command("gate")
def gate(
    verdict: str = typer.Argument(..., help="reviewer verdict JSON"),
    regime: Optional[Path] = typer.Option(
        None, "--regime", help="optional regime.json to validate next_state"
    ),
) -> None:
    """Validate a reviewer verdict JSON against the deterministic gate."""
    try:
        raw = json.loads(verdict)
        v = parse_reviewer_verdict(raw)
    except Exception as exc:
        _fail(f"parse error: {exc}")

    valid_nodes = None
    if regime:
        valid_nodes = set(load_regime(regime).flow.nodes)

    result = gate_reviewer_verdict(v, valid_nodes)
    if result.ok:
        _ok(f"gate passed: action=[bold]{v.action}[/bold] verdict=[bold]{v.verdict}[/bold]", markup=True)
    else:
        _fail(f"gate rejected: {result.reason}")


# ---------------------------------------------------------------------------
# status
# ---------------------------------------------------------------------------
@app.command("status")
def status(
    base: str = typer.Option(Settings().base_url, "--base", help="worker URL"),
    json_out: bool = typer.Option(False, "--json", help="machine-readable JSON"),
) -> None:
    """Check worker health."""
    client = OpenCodeClient(base)
    healthy = client.health()
    if json_out:
        _emit_json({"healthy": healthy, "base": base})
        return
    if healthy:
        _ok(f"worker healthy at [bold]{base}[/bold]", markup=True)
    else:
        _fail(f"worker unhealthy at {base}")


# ---------------------------------------------------------------------------
# sessions
# ---------------------------------------------------------------------------
@app.command("sessions")
def sessions(
    base: str = typer.Option(Settings().base_url, "--base", help="worker URL"),
    clean: bool = typer.Option(False, "--clean", help="abort all sessions"),
    kill: Optional[str] = typer.Option(None, "--kill", help="abort a specific session id"),
    json_out: bool = typer.Option(False, "--json", help="machine-readable JSON"),
    perm: str = typer.Option("read", "--perm", help="held permission level "
                             "(read|interact|run|clean); gates write ops"),
) -> None:
    """List all opencode sessions on the worker with their live status."""
    _gate(perm, ["sessions"]
          + (["--clean"] if clean else []) + (["--kill", kill] if kill else []))
    client = OpenCodeClient(base)
    if kill:
        try:
            client.abort_session(kill)
        except Exception as exc:
            _fail(f"abort {kill} failed: {exc}")
        if json_out:
            _emit_json({"aborted": kill})
            return
        _ok(f"aborted session {kill}", markup=False)
        return
    slist = client.list_sessions()
    if clean:
        ids = [s.get("id") for s in slist if s.get("id")]
        for sid in ids:
            try:
                client.abort_session(sid)
            except Exception as exc:
                console.print(f"[dim]abort {sid} failed: {exc}[/dim]")
        if json_out:
            _emit_json({"aborted": len(ids)})
            return
        _ok(f"aborted {len(ids)} sessions", markup=False)
        return
    busy = client.session_status_map()
    if json_out:
        rows = [{
            "id": s.get("id"), "title": s.get("title"), "agent": s.get("agent"),
            "status": busy.get(s.get("id")) or "idle",
            "tokens_in": (s.get("tokens") or {}).get("input") or 0,
            "tokens_out": (s.get("tokens") or {}).get("output") or 0,
        } for s in slist]
        _emit_json({"sessions": rows})
        return
    table = Table(title="worker sessions", show_header=True)
    table.add_column("session", style="bold cyan")
    table.add_column("title")
    table.add_column("agent")
    table.add_column("status")
    table.add_column("tokens")
    for s in slist:
        sid = s.get("id", "?")
        st = busy.get(sid) or "idle"
        style = "bold yellow" if st == "busy" else "green"
        toks = s.get("tokens") or {}
        tin = toks.get("input") or 0
        tout = toks.get("output") or 0
        table.add_row(sid, str(s.get("title") or "")[:28],
                      str(s.get("agent") or ""), Text(st, style=style),
                      f"{tin}+{tout}")
    console.print(table)
    console.print(f"[dim]{len(slist)} sessions[/dim]")


# ---------------------------------------------------------------------------
# dialog
# ---------------------------------------------------------------------------
@app.command("dialog")
def dialog(
    base: str = typer.Option(Settings().base_url, "--base", help="worker URL"),
    live: bool = typer.Option(
        False, "--live", help="use the real worker (else offline MockClient)"),
    model: str = typer.Option(Settings().model, "--model", help="model for LLM explain"),
    perm: str = typer.Option("run", "--perm", help="held permission level "
                             "(read|interact|run|clean); gates write ops"),
) -> None:
    """Open the God Dialog: one natural-language control/monitor surface.

    In the 'God>' prompt you can (Chinese/English both work):
      status | monitor [field]      live workflow snapshot
      watch [n] [topic]             recent events (watchdog/blackboard/notify)
      start [flow] <task>           non-blockingly launch a workflow
      inspect <workflow_id>         show a workflow's blackboard metrics
      talk <session> <message>      interact with a specific opencode session
      design <flow> <json|text>     design & register a new workflow
      config | help | quit          settings / help / exit
    Free-form text is explained by the LLM when --live (worker-thread, async).
    """
    from ..app.dialog_app import run_dialog

    _gate(perm, ["dialog"])
    from ..infra.permission import PermissionLevel

    # write capability only if the effective held level is at least run;
    # never unconditional (fixes privilege escalation)
    can_write = _effective_held(perm) >= PermissionLevel.RUN
    run_dialog(base, model, live=live, print_fn=lambda s: console.print(s),
               allow_write=can_write)


# ---------------------------------------------------------------------------
# session (subcommands: send / reply)
# ---------------------------------------------------------------------------
_session_app = typer.Typer(help="Interact with a specific opencode session.")


@_session_app.command("send")
def session_send(
    session_id: str = typer.Argument(..., help="opencode session id"),
    message: str = typer.Argument(..., help="message to send to the session"),
    base: str = typer.Option(Settings().base_url, "--base", help="worker URL"),
    reply: bool = typer.Option(False, "--reply", help="also print the assistant reply"),
    agent: str = typer.Option("developer", "--agent", help="agent to send as"),
    json_out: bool = typer.Option(False, "--json", help="machine-readable JSON"),
    timeout: float = typer.Option(120.0, "--timeout", help="max wait for reply (s)"),
    perm: str = typer.Option("interact", "--perm", help="held permission level "
                             "(read|interact|run|clean); gates write ops"),
) -> None:
    """Send a message to a specific opencode session (independent interaction)."""
    _gate(perm, ["session", "send"])
    client = OpenCodeClient(base, timeout=timeout)
    client.send_message(session_id, message, agent)
    if not reply:
        if json_out:
            _emit_json({"sent": True, "session": session_id})
            return
        _ok(f"sent message to session {session_id}", markup=False)
        return
    # wait for the newest assistant reply
    deadline = time.time() + timeout
    latest = ""
    while time.time() < deadline:
        try:
            msgs = client.read_messages(session_id)
        except Exception:
            msgs = []
        for m in reversed(msgs):
            if getattr(m, "role", None) == "assistant" and (m.reply or m.text).strip():
                latest = (m.reply or m.text).strip()
                break
        if latest:
            break
        time.sleep(1)
    if json_out:
        _emit_json({"sent": True, "session": session_id, "reply": latest})
        return
    if latest:
        _ok(f"sent; reply:\n{latest}", markup=False)
    else:
        _fail(f"sent but no reply within {timeout:.0f}s")


@_session_app.command("reply")
def session_reply(
    session_id: str = typer.Argument(..., help="opencode session id"),
    base: str = typer.Option(Settings().base_url, "--base", help="worker URL"),
    json_out: bool = typer.Option(False, "--json", help="machine-readable JSON"),
) -> None:
    """Print the newest assistant reply of a session."""
    client = OpenCodeClient(base, timeout=30)
    try:
        msgs = client.read_messages(session_id)
    except Exception as exc:
        _fail(f"read {session_id} failed: {exc}")
    latest = ""
    for m in reversed(msgs):
        if getattr(m, "role", None) == "assistant" and (m.reply or m.text).strip():
            latest = (m.reply or m.text).strip()
            break
    if json_out:
        _emit_json({"session": session_id, "reply": latest})
        return
    if latest:
        console.print(latest)
    else:
        _ok("no assistant reply yet", markup=False)


app.add_typer(_session_app, name="session")


# ---------------------------------------------------------------------------
# task (subcommands: submit / list / status / stop / logs / clean)
# ---------------------------------------------------------------------------
_task_app = typer.Typer(help="Supervised-task registry (replaces ops/oc-task.py).")


@_task_app.command("list")
def task_list(
    json_out: bool = typer.Option(False, "--json", help="machine-readable JSON"),
) -> None:
    """List supervised tasks with live status (single derive)."""
    from ..task import TaskRegistry

    tasks = TaskRegistry().list()
    if json_out:
        _emit_json({"tasks": tasks})
        return
    for t in tasks:
        st = t["status"]
        style = "bold yellow" if st == "running" else (
            "green" if st == "done" else "bold red")
        console.print(f"  {t['id']} [{style}]{st}[/{style}] "
                      f"outcome={t.get('outcome')} goal={(t.get('goal') or '')[:40]}")


@_task_app.command("status")
def task_status(
    task_id: str = typer.Argument(..., help="task id"),
    json_out: bool = typer.Option(False, "--json", help="machine-readable JSON"),
) -> None:
    """Show one task's status and summary."""
    from ..task import TaskRegistry

    rec = TaskRegistry().get(task_id)
    if rec is None:
        _fail(f"unknown task: {task_id}")
    if json_out:
        _emit_json(rec)
        return
    console.print(f"task {task_id} · status={rec['status']} outcome={rec.get('outcome')}")
    console.print(f"  goal: {rec.get('goal') or '-'}")


@_task_app.command("logs")
def task_logs(
    task_id: str = typer.Argument(..., help="task id"),
) -> None:
    """Print a task's captured output."""
    from ..task import TaskRegistry

    console.print(TaskRegistry().logs(task_id))


@_task_app.command("stop")
def task_stop(
    task_id: str = typer.Argument(..., help="task id"),
) -> None:
    """Stop a running task (SIGTERM its supervisor)."""
    from ..task import TaskRegistry

    if TaskRegistry().stop(task_id):
        _ok(f"stopped {task_id}", markup=False)
    else:
        _fail(f"unknown task: {task_id}")


@_task_app.command("clean")
def task_clean(
    task_id: str = typer.Argument(..., help="task id"),
) -> None:
    """Delete a task's records (json/out/summary)."""
    from ..task import TaskRegistry

    TaskRegistry().clean(task_id)
    _ok(f"cleaned {task_id}", markup=False)


app.add_typer(_task_app, name="task")


# ---------------------------------------------------------------------------
# job (subcommands: list / status) — async job registry
# ---------------------------------------------------------------------------
_job_app = typer.Typer(help="Query background async jobs (run/run-many --async).")


@_job_app.command("list")
def job_list(
    running: bool = typer.Option(False, "--running", help="only running jobs"),
    json_out: bool = typer.Option(False, "--json", help="machine-readable JSON"),
) -> None:
    """List submitted background jobs with their live status."""
    from ..infra.jobs import JobRegistry, public_record

    records = [public_record(r) for r in JobRegistry().list(include_all=not running)]
    if json_out:
        _emit_json({"jobs": records})
        return
    if not records:
        _ok("no jobs", markup=False)
        return
    table = Table(title="regime jobs", show_header=True)
    table.add_column("id", style="bold cyan")
    table.add_column("type")
    table.add_column("title")
    table.add_column("status")
    table.add_column("pid")
    for r in records:
        status = r["status"]
        style = "bold yellow" if status == "running" else (
            "green" if status == "done" else "bold red")
        table.add_row(r["id"], str(r["type"]), str(r["title"] or "")[:24],
                      Text(status, style=style), str(r.get("pid") or ""))
    console.print(table)
    console.print(f"[dim]{len(records)} jobs[/dim]")


@_job_app.command("status")
def job_status(
    job_id: str = typer.Argument(..., help="job id from `regime run --async`"),
    json_out: bool = typer.Option(False, "--json", help="machine-readable JSON"),
) -> None:
    """Show the status and (if finished) the result of a background job."""
    from ..infra.jobs import JobRegistry, public_record

    record = JobRegistry().get(job_id)
    if record is None:
        _fail(f"unknown job: {job_id}")
    pub = public_record(record)
    if json_out:
        _emit_json(pub)
        return
    status = pub["status"]
    style = "bold yellow" if status == "running" else (
        "green" if status == "done" else "bold red")
    console.print(f"job [bold]{pub['id']}[/bold] · type={pub['type']} · "
                  f"status=[{style}]{status}[/{style}]")
    if pub.get("title"):
        console.print(f"  title: {pub['title']}")
    if pub.get("ledger"):
        console.print(f"  ledger: {pub['ledger']}")
    result = pub.get("result")
    if result is not None:
        outcome = result.get("outcome") or (
            "ok" if result.get("ok") else "?")
        console.print(f"  outcome: {outcome}")
        if result.get("elapsed_sec") is not None:
            console.print(f"  elapsed: {result['elapsed_sec']}s")
    elif status == "running":
        _ok(f"still running (pid={pub.get('pid')})", markup=False)


app.add_typer(_job_app, name="job")


# ---------------------------------------------------------------------------
# events
# ---------------------------------------------------------------------------
@app.command("events")
def events(
    ledger: str = typer.Option(None, "--ledger", help="path to JSONL event ledger"),
    follow: bool = typer.Option(False, "--follow", help="tail new events (like tail -f)"),
) -> None:
    """Read (or tail) the JSONL event ledger, one JSON event per line.

    Events are written by `regime run/run-many --ledger <path>` and by the
    runtime's Ledger. This is the event-stream surface for the dialog carrier.
    """
    path = ledger or (Settings().ledger_path or None)
    if not path:
        _fail("no ledger path (pass --ledger, or set ledger_path in config)")
    import os
    if not os.path.exists(path):
        _fail(f"ledger not found: {path}")

    def _emit(line: str) -> None:
        line = line.strip()
        if line:
            console.print(line)  # already JSON

    if not follow:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                _emit(line)
        return
    # tail -f semantics over the JSONL ledger
    with open(path, encoding="utf-8") as fh:
        fh.seek(0, os.SEEK_END)
        while True:
            line = fh.readline()
            if line:
                _emit(line)
            else:
                time.sleep(0.5)


if __name__ == "__main__":
    app()