"""regime-driver CLI (typer + rich)."""

from __future__ import annotations

import json
import os
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
    flow: str = typer.Option(None, "--flow", help="run a named flow from the FlowRegistry "
                             "(designed/loaded; resolves to its persisted spec)"),
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
            *(["--flow", flow] if flow else []),
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
    sm = _sm_from_flow_or_regime(flow, regime)
    if not no_preflight:
        from ..app.preflight import preflight

        res = preflight(sm, timeout_sec=30.0)
        if json_out:
            _emit_json({"preflight": res, "started": False})
        if not res["ok"]:
            _fail(f"preflight FAILED: outcome={res['outcome']} detail={res['detail']}")
        else:
            _ok(f"preflight PASSED (offline outcome={res['outcome']})", markup=False)
    _run(settings, context, title, json_out=json_out, reporter=reporter, sm=sm)


def _sm_from_flow_or_regime(flow: str | None, regime: Path | None):
    """Resolve the StateMachine to run: a named registry flow or a regime file.

    ``--flow`` takes precedence (God-Dialog-designed flows); ``--regime`` is the
    file-based fallback; neither means the packaged default descriptor.
    """
    from ..core.state_machine import StateMachineError

    if flow:
        try:
            return _default_registry().get(flow).sm
        except (AttributeError, KeyError) as exc:
            _fail(f"unknown flow '{flow}' (use `regime flow list`)")
    try:
        return load_regime(regime)
    except (StateMachineError, FileNotFoundError) as exc:
        _fail(f"error loading regime: {exc}")


def _run(settings: Settings, context: str, title: str, json_out: bool = False,
         reporter: Optional[Path] = None, sm: "StateMachine | None" = None) -> None:
    if sm is None:
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
# drive (one-command self-driving stack: run + supervisor + reporter)
# ---------------------------------------------------------------------------
@app.command("drive")
def drive(
    context: str = typer.Argument(..., help="task context injected into developer nodes"),
    base: str = typer.Option(None, "--base", help="worker opencode server URL"),
    config: Optional[Path] = typer.Option(None, "--config", help="config file (JSON/TOML)"),
    regime: Optional[Path] = typer.Option(None, "--regime", help="path to regime.json"),
    deadline: int = typer.Option(None, "--deadline", help="global deadline (sec) for the whole drive"),
    container: str = typer.Option(
        None, "--container", help="worker docker container name (for L4 restart on T1)"),
    stall: int = typer.Option(60, "--stall", help="session-stall detection seconds (T2)"),
    meta: bool = typer.Option(
        False, "--meta", help="enable intelligent meta-analysis (real model judges a stall)"),
    meta_model: str = typer.Option(
        Settings().model, "--meta-model", help="model for meta-analysis"),
    reporter: Optional[Path] = typer.Option(
        None, "--reporter", help="append-only report journal path (single truth)"),
    ledger: Optional[Path] = typer.Option(
        None, "--ledger", help="JSONL event ledger path (workflow events)"),
    flow: str = typer.Option(None, "--flow", help="run a named flow from the FlowRegistry "
                             "(designed/loaded; resolves to its persisted spec)"),
    tasks_dir: Optional[Path] = typer.Option(
        None, "--tasks-dir", help="supervised-task registry dir (default: ~/.regime/tasks)"),
    skills_dir: Optional[Path] = typer.Option(
        None, "--skills-dir", help="path to workflow-regime skills dir"),
    workspace: str = typer.Option(
        None, "--workspace", help="run in a dedicated per-workspace worker instance "
        "(created/reused; physical isolation from other workspaces)"),
    json_out: bool = typer.Option(False, "--json", help="machine-readable JSON result"),
    async_run: bool = typer.Option(
        False, "--async", help="submit as a background supervised task and return a handle"),
    perm: str = typer.Option("run", "--perm", help="held permission level "
                             "(read|interact|run|clean); gates write ops"),
    no_preflight: bool = typer.Option(
        False, "--no-preflight", help="SKIP the mandatory offline preflight trial (not recommended)"),
) -> None:
    """Bring up the whole self-driving stack with one command.

    Runs the workflow executor AND the process-external supervisor (independent
    clock: T1 health/L4 restart, T2 session stall, deadline, correction ladder)
    sharing ONE reporter journal, registered as a supervised task. Preflight is
    mandatory (offline trial) unless --no-preflight. Pass --async to run it as a
    tracked background task (`regime task list/status`). Pass --workspace <ws> to
    run in a dedicated per-workspace worker instance (physical isolation).
    """
    _gate(perm, ["drive", context])
    from ..task import TaskRegistry
    from ..app.reporter import Reporter

    settings = load_settings(
        config_file=config,
        overrides={
            "base_url": base,
            "regime_path": str(regime) if regime else None,
            "default_deadline_sec": deadline,
            "ledger_path": str(ledger) if ledger else None,
            "skills_dir": str(skills_dir) if skills_dir else None,
        },
    )
    if async_run:
        argv = [
            "drive", context,
            *(["--base", base] if base else []),
            *(["--config", str(config)] if config else []),
            *(["--regime", str(regime)] if regime else []),
            *(["--flow", flow] if flow else []),
            *(["--deadline", str(deadline)] if deadline is not None else []),
            *(["--container", container] if container else []),
            *(["--stall", str(stall)] if stall != 60 else []),
            *(["--reporter", str(reporter)] if reporter else []),
            *(["--ledger", str(ledger)] if ledger else []),
            *(["--tasks-dir", str(tasks_dir)] if tasks_dir else []),
            *(["--skills-dir", str(skills_dir)] if skills_dir else []),
            *(["--workspace", workspace] if workspace else []),
            *(["--no-preflight"] if no_preflight else []),
        ]
        registry = TaskRegistry(tasks_dir or TaskRegistry().dir)
        rec = registry.submit(
            [sys.executable, "-m", "regime_driver.cli", *argv],
            goal=context, deadline=deadline)
        if json_out:
            _emit_json({"submitted": True, "task": rec["id"],
                        "cmd": "regime task status " + rec["id"]})
        else:
            _ok(f"drive task [bold]{rec['id']}[/bold] submitted "
                f"(pid={rec['pid']})", markup=True)
            _ok(f"status: regime task status {rec['id']}", markup=False)
        return

    # mandatory preflight (offline trial) before touching a real worker/session
    sm = _sm_from_flow_or_regime(flow, regime)
    if not no_preflight:
        from ..app.preflight import preflight

        res = preflight(sm, timeout_sec=30.0)
        if not res["ok"]:
            _fail(f"preflight FAILED: outcome={res['outcome']} detail={res['detail']}")
        _ok(f"preflight PASSED (offline outcome={res['outcome']})", markup=False)

    from ..drive import Drive

    # resolve the worker base: a dedicated per-workspace instance (if requested)
    # gives physical isolation; otherwise fall back to the configured --base.
    if workspace:
        from ..worker import WorkerPool
        wi = WorkerPool().ensure(workspace)
        settings = settings.model_copy(update={"base_url": wi.base_url})
        _ok(f"workspace '{workspace}' instance: {wi.base_url}", markup=False)
    client = OpenCodeClient(settings.base_url, model=settings.model,
                            timeout=settings.request_timeout)
    journal = str(reporter) if reporter else None
    rep = Reporter(journal_path=journal, project_id="drive")
    # register the running stack as a supervised task (tracked/stoppable/reportable)
    registry = TaskRegistry(tasks_dir or TaskRegistry().dir)
    # an async-launched drive re-enters here: reuse the parent's task id so the
    # run reports under ONE record (no duplicate task / orphaned "crashed").
    rec = registry.register(goal=context, deadline=deadline,
                            pid=os.getpid(),
                            task_id=os.environ.get("REGIME_TASK_ID"))
    drv = Drive(
        settings, sm, client, rep, container=container,
        deadline_sec=deadline, stall_sec=stall,
        meta_enabled=meta, meta_model=meta_model,
    )
    try:
        # render live progress in the foreground
        import threading
        result: dict = {}
        def _go() -> None:
            try:
                result["res"] = drv.run(context)
            finally:
                rep.close()
        t = threading.Thread(target=_go, daemon=True)
        t0 = time.time()
        t.start()
        try:
            from rich.live import Live
            from rich.table import Table
            with Live(console=console, refresh_per_second=4) as live:
                while t.is_alive():
                    table = Table(title=f"drive · {time.time()-t0:.0f}s · {rec['id']}",
                                  show_header=False)
                    table.add_column(justify="right")
                    table.add_column()
                    wf = getattr(drv.driver, "workflow", None)
                    node = getattr(wf, "_node", None) or "?"
                    state = getattr(wf, "_state", None) or "?"
                    table.add_row("node", node)
                    table.add_row("state", state)
                    table.add_row("session", getattr(drv, "_session_id", None) or "?")
                    live.update(table)
                    time.sleep(0.25)
        except KeyboardInterrupt:
            pass
        t.join(timeout=5)
        if "res" not in result:
            _fail("drive did not complete")
        dr = result["res"]
        # write the supervised-task summary for report/registry completion
        _write_drive_summary(rec["summary_file"], dr.to_dict())
        if json_out:
            _emit_json({"task": rec["id"], **dr.to_dict()})
            if dr.outcome != Outcome.COMPLETE.value:
                raise typer.Exit(1)
            return
        mark = "✓" if dr.outcome == Outcome.COMPLETE.value else "✗"
        console.print(f"  {mark} outcome: {dr.outcome} @ {dr.end or '?'} "
                      f"({dr.elapsed_sec}s)")
        console.print(f"  supervisor: {dr.supervisor}  session: {dr.session_id or '-'}")
        if dr.outcome == Outcome.COMPLETE.value:
            _ok(f"drive task {rec['id']} completed", markup=False)
        else:
            _fail(f"drive {dr.outcome} at {dr.end or '?'}"
                  + (f": {dr.detail}" if dr.detail else ""), markup=True)
    finally:
        rep.close()


def _write_drive_summary(summary_file: str, data: dict) -> None:
    """Write the supervised-task summary JSON (marks a task 'done')."""
    import os
    try:
        os.makedirs(os.path.dirname(summary_file), exist_ok=True)
        with open(summary_file, "w", encoding="utf-8") as fh:
            fh.write(json.dumps(data, ensure_ascii=False))
    except OSError:
        pass


# ---------------------------------------------------------------------------
# drive-many (concurrent isolated fleet: N full-stack drives, one per workspace)
# ---------------------------------------------------------------------------
@app.command("drive-many")
def drive_many(
    contexts: list[str] = typer.Argument(..., help="one task context per fleet member"),
    workspaces: str = typer.Option(
        None, "--workspaces", "-w", help="comma-separated workspaces, one per task "
        "(auto-assigned if fewer; each task runs in its own isolated worker instance)"),
    workers: int = typer.Option(
        None, "--workers", help="max concurrent fleet members (default: all at once)"),
    base: str = typer.Option(None, "--base", help="ignored when --workspaces used"),
    config: Optional[Path] = typer.Option(None, "--config", help="config file (JSON/TOML)"),
    regime: Optional[Path] = typer.Option(None, "--regime", help="path to regime.json"),
    deadline: int = typer.Option(None, "--deadline", help="global deadline (sec) per fleet member"),
    reporter: Optional[Path] = typer.Option(
        None, "--reporter", help="append-only report journal path (single truth for the fleet)"),
    skills_dir: Optional[Path] = typer.Option(
        None, "--skills-dir", help="path to workflow-regime skills dir"),
    meta: bool = typer.Option(
        False, "--meta", help="enable intelligent meta-analysis (real model judges a stall)"),
    meta_model: str = typer.Option(
        Settings().model, "--meta-model", help="model for meta-analysis"),
    json_out: bool = typer.Option(False, "--json", help="machine-readable JSON result"),
    perm: str = typer.Option("run", "--perm", help="held permission level "
                             "(read|interact|run|clean); gates write ops"),
    no_preflight: bool = typer.Option(
        False, "--no-preflight", help="SKIP the mandatory offline preflight trial (not recommended)"),
) -> None:
    """Run a fleet of isolated full-stack drives in parallel.

    Each task runs in its OWN workspace worker instance (physical isolation via
    the multi-instance WorkerPool), sharing ONE reporter journal. This is the
    concurrent-self-driving entry: multiple tasks can run simultaneously without
    clobbering each other's files.
    """
    _gate(perm, ["drive-many", *contexts])
    from ..app.preflight import preflight
    from ..app.reporter import Reporter
    from ..core.state_machine import StateMachineError
    from ..fleet import Fleet, FleetTask

    settings = load_settings(
        config_file=config,
        overrides={
            "base_url": base,
            "regime_path": str(regime) if regime else None,
            "default_deadline_sec": deadline,
            "skills_dir": str(skills_dir) if skills_dir else None,
        },
    )
    try:
        sm = load_regime(regime)
    except (StateMachineError, FileNotFoundError) as exc:
        _fail(f"error loading regime: {exc}")
    if not no_preflight:
        res = preflight(sm, timeout_sec=30.0)
        if not res["ok"]:
            _fail(f"preflight FAILED: outcome={res['outcome']} detail={res['detail']}")
        _ok(f"preflight PASSED (offline outcome={res['outcome']})", markup=False)

    task_ids = [f"w{i + 1}" for i in range(len(contexts))]
    requested = [w.strip() for w in (workspaces or "").split(",") if w.strip()]
    ws = Fleet.auto_workspaces(task_ids, requested)
    tasks = [FleetTask(task_ids[i], contexts[i], ws[i])
             for i in range(len(contexts))]
    journal = str(reporter) if reporter else None
    rep = Reporter(journal_path=journal, project_id="fleet")
    fleet = Fleet(
        settings, sm, rep, deadline_sec=deadline,
        meta_enabled=meta, meta_model=meta_model,
    )
    try:
        _ok(f"fleet of {len(tasks)} starting: {', '.join(f'{t.task_id}@{t.workspace}' for t in tasks)}",
            markup=False)
        results = fleet.run(tasks, worker_count=workers)
        if json_out:
            _emit_json({"results": {tid: dr.to_dict() for tid, dr in results.items()}})
            if any(dr.outcome != Outcome.COMPLETE.value for dr in results.values()):
                raise typer.Exit(1)
            return
        print(f"\n=== drive-many fleet 结果 ({len(results)} tasks) ===")
        ws_by_id = {t.task_id: t.workspace for t in tasks}
        for tid, dr in results.items():
            mark = "✓" if dr.outcome == Outcome.COMPLETE.value else "✗"
            console.print(f"  {mark} {tid} @ {ws_by_id.get(tid, '?')}: {dr.outcome} "
                          f"({dr.elapsed_sec}s) supervisor={dr.supervisor}")
        bad = [tid for tid, dr in results.items()
               if dr.outcome != Outcome.COMPLETE.value]
        if bad:
            _fail(f"{len(bad)} fleet member(s) not complete: {', '.join(bad)}", markup=False)
        _ok(f"all {len(results)} fleet members done", markup=False)
    finally:
        rep.close()


# ---------------------------------------------------------------------------
# doctor (usability self-check: model/key/worker readiness + guidance)
# ---------------------------------------------------------------------------
@app.command("doctor")
def doctor(
    base: str = typer.Option(Settings().base_url, "--base", help="worker URL"),
    json_out: bool = typer.Option(False, "--json", help="machine-readable JSON"),
) -> None:
    """Self-check readiness: worker health, model config, API key presence.

    Read-only. Reports whether the configured model + key are likely usable and
    prints context-appropriate next steps (containerized worker vs host opencode).
    Never prints API keys — only presence.
    """
    import os as _os
    from pathlib import Path as _Path

    from ..infra.settings import Settings

    settings = Settings(base_url=base)
    model = settings.model
    provider = model.split("/")[0] if "/" in model else model
    checks: list[dict] = []

    # 1) worker health
    try:
        healthy = OpenCodeClient(base, timeout=5).health()
    except Exception:
        healthy = False
    checks.append({"check": "worker health", "ok": healthy, "base": base})

    # 2) key readiness (presence only, never the value)
    def _key_file(name: str) -> bool:
        return _Path.home().joinpath(".regime", "keys", name).exists()

    env_map = {"my-opencode-go": ("OPENCODE_GO_API_KEY", "opencode-go.key"),
               "deepseek-api": ("DEEPSEEK_API_KEY", "deepseek.key")}
    env_name, file_name = env_map.get(provider, (None, None))
    if env_name:
        has_env = bool(_os.environ.get(env_name))
        has_file = _key_file(file_name)
        checks.append({"check": f"key for {provider}", "ok": has_env or has_file,
                       "env": has_env, "key_file": has_file})
    auth_has_go = False
    try:
        auth = json.loads(_Path.home().joinpath(
            ".local", "share", "opencode", "auth.json").read_text(encoding="utf-8"))
        auth_has_go = ("opencode-go" in auth or "my-opencode-go" in auth
                       or "deepseek-api" in auth or "deepseek" in auth)
    except Exception:
        pass
    checks.append({"check": "opencode auth.json has key", "ok": auth_has_go})

    all_ok = all(c["ok"] for c in checks)
    if json_out:
        _emit_json({"model": model, "provider": provider, "ok": all_ok,
                    "checks": checks})
        if not all_ok:
            raise typer.Exit(1)
        return

    console.print(f"[bold]regime doctor[/bold] · model={model}")
    for c in checks:
        mark = "✓" if c["ok"] else "✗"
        detail = " ".join(f"{k}={v}" for k, v in c.items() if k not in ("check", "ok"))
        console.print(f"  {mark} {c['check']} {detail}")
    if not all_ok:
        console.print("\n[bold]建议：[/bold]")
        if not healthy:
            console.print("  · 容器化：`ops/up.sh all`（构建+起 worker/god）")
            console.print("  · 或主机模式：`regime run --base <主机 opencode 端口>`")
        if provider == "my-opencode-go" and not checks[1]["ok"]:
            console.print("  · 设 OPENCODE_GO_API_KEY 或写 ~/.regime/keys/opencode-go.key")
        if provider == "deepseek-api" and not checks[1]["ok"]:
            console.print("  · 设 DEEPSEEK_API_KEY 或写 ~/.regime/keys/deepseek.key")
        raise typer.Exit(1)
    console.print("\n✓ 配置就绪：可用 `regime run/drive`（默认模型 deepseek-api）")


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
    meta: bool = typer.Option(
        False, "--meta", help="enable intelligent meta-analysis (real model judges the stall)"),
    meta_model: str = typer.Option(
        Settings().model, "--meta-model", help="model for meta-analysis"),
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
    (DESIGN-supervision.md). Pass --meta to let a real model judge a stall
    (deterministically gated); otherwise the ladder is fully deterministic.
    """
    from ..app.reporter import Reporter
    from ..supervisor import Supervisor

    client = OpenCodeClient(base, model=Settings().model)
    rep = Reporter(journal_path=reporter) if reporter else Reporter(project_id="supervisor")
    sup = Supervisor(
        client, rep, container=container, stall_sec=stall,
        deadline_sec=deadline if deadline else None,
        session_id=session or None, goal="",
        meta_enabled=meta, meta_model=meta_model,
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

        # the skill-loadability check is only meaningful when a skills dir is
        # provided; without it we cannot verify skills (e.g. a deployed container
        # without the repo tree) so we skip that check rather than hard-fail.
        deep_res = deep_validate(
            sm,
            load_skill=(lambda name: load_skill(name, str(skills_dir)))
            if skills_dir else None,
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
    deep: bool = typer.Option(
        False, "--deep", help="aggregate situational summary: sessions + flows + tasks + reporter rollup"),
    reporter: Optional[Path] = typer.Option(
        None, "--reporter", help="report journal path to include its rollup (with --deep)"),
    tasks_dir: Optional[Path] = typer.Option(
        None, "--tasks-dir", help="supervised-task registry dir (with --deep)"),
    json_out: bool = typer.Option(False, "--json", help="machine-readable JSON"),
) -> None:
    """Check worker health; with --deep, an aggregate situational summary.

    ``--deep`` returns everything the God Dialog needs to judge global state in
    one call: worker health, live sessions, registered flows, supervised tasks,
    and (with --reporter) the report-bus rollup. Read-only.
    """
    client = OpenCodeClient(base)
    healthy = client.health()
    if not deep:
        if json_out:
            _emit_json({"healthy": healthy, "base": base})
            return
        if healthy:
            _ok(f"worker healthy at [bold]{base}[/bold]", markup=True)
        else:
            _fail(f"worker unhealthy at {base}")
        return

    # --deep: aggregate situational summary ----------------------------------
    summary: dict = {"healthy": healthy, "base": base}
    sessions_rows: list = []
    if healthy:
        try:
            slist = client.list_sessions()
            status_map = client.session_status_map()
            sessions_rows = [{
                "id": s.get("id"), "title": s.get("title"), "agent": s.get("agent"),
                "status": status_map.get(s.get("id")) or "idle",
                "tokens_in": (s.get("tokens") or {}).get("input") or 0,
                "tokens_out": (s.get("tokens") or {}).get("output") or 0,
            } for s in slist]
        except Exception:
            # a partially-degraded worker must not kill the whole situational view
            sessions_rows = []
    summary["sessions"] = sessions_rows
    summary["busy_sessions"] = sum(
        1 for s in sessions_rows if s["status"] == "busy")

    reg = _default_registry()
    summary["flows"] = [e.to_dict() for e in reg.list()]

    from ..task import DEFAULT_TASKS_DIR, TaskRegistry
    # read-only aggregation: never create the tasks dir as a side effect
    tasks_dir_path = Path(tasks_dir) if tasks_dir else Path(DEFAULT_TASKS_DIR)
    if tasks_dir_path.exists():
        summary["tasks"] = TaskRegistry(tasks_dir_path).list()
    else:
        summary["tasks"] = []

    if reporter:
        from ..app.reporter import Reporter
        rep = Reporter(journal_path=reporter)
        try:
            rep.load()  # replay the journal so rollup reflects the on-disk truth
            summary["reporter"] = {
                "rollup": rep.rollup(),
                "records": len(rep.journal_slice()),
            }
        finally:
            rep.close()

    if json_out:
        _emit_json(summary)
        return
    console.print(f"worker: [bold]{'healthy' if healthy else 'UNHEALTHY'}[/bold] @ {base}")
    if healthy:
        console.print(f"sessions: {len(summary['sessions'])} "
                      f"([bold yellow]{summary['busy_sessions']} busy[/bold yellow])")
    console.print(f"flows: {len(summary['flows'])} → "
                  + ", ".join(f"{e['name']}({e['nodes']})" for e in summary["flows"]))
    console.print(f"tasks: {len(summary['tasks'])} "
                  + f"([bold yellow]{sum(1 for t in summary['tasks'] if t['status']=='running')} running[/bold yellow])")
    if reporter:
        r = summary.get("reporter") or {}
        console.print(f"reporter: {r.get('records', 0)} records "
                      f"([dim]{len(r.get('rollup') or [])} rollup groups[/dim])")


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
    tasks_dir: Optional[Path] = typer.Option(
        None, "--tasks-dir", help="supervised-task registry dir (default: ~/.regime/tasks)"),
    json_out: bool = typer.Option(False, "--json", help="machine-readable JSON"),
) -> None:
    """List supervised tasks with live status (single derive)."""
    from ..task import TaskRegistry

    tasks = TaskRegistry(tasks_dir).list()
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
    tasks_dir: Optional[Path] = typer.Option(
        None, "--tasks-dir", help="supervised-task registry dir (default: ~/.regime/tasks)"),
    json_out: bool = typer.Option(False, "--json", help="machine-readable JSON"),
) -> None:
    """Show one task's status and summary."""
    from ..task import TaskRegistry

    rec = TaskRegistry(tasks_dir).get(task_id)
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
    tasks_dir: Optional[Path] = typer.Option(
        None, "--tasks-dir", help="supervised-task registry dir (default: ~/.regime/tasks)"),
) -> None:
    """Print a task's captured output."""
    from ..task import TaskRegistry

    console.print(TaskRegistry(tasks_dir).logs(task_id))


@_task_app.command("stop")
def task_stop(
    task_id: str = typer.Argument(..., help="task id"),
    tasks_dir: Optional[Path] = typer.Option(
        None, "--tasks-dir", help="supervised-task registry dir (default: ~/.regime/tasks)"),
) -> None:
    """Stop a running task (SIGTERM its supervisor)."""
    from ..task import TaskRegistry

    if TaskRegistry(tasks_dir).stop(task_id):
        _ok(f"stopped {task_id}", markup=False)
    else:
        _fail(f"unknown task: {task_id}")


@_task_app.command("clean")
def task_clean(
    task_id: str = typer.Argument(..., help="task id"),
    tasks_dir: Optional[Path] = typer.Option(
        None, "--tasks-dir", help="supervised-task registry dir (default: ~/.regime/tasks)"),
) -> None:
    """Delete a task's records (json/out/summary)."""
    from ..task import TaskRegistry

    TaskRegistry(tasks_dir).clean(task_id)
    _ok(f"cleaned {task_id}", markup=False)


app.add_typer(_task_app, name="task")


# ---------------------------------------------------------------------------
# flow (subcommands: list / validate / load / reload / rm / inspect)
#   hot flow-definition lifecycle (WORK_PLAN5 F1-F11)
# ---------------------------------------------------------------------------
_flow_app = typer.Typer(
    help="FlowRegistry: hot compile/validate/load/reload of named flows.")

# Lazily-seeded shared registry, scoped to THIS process (a fresh regime process
# gets its own registry; each `regime flow` invocation re-derives from disk).
# Not shared with the god-dialog process — see dialog_app which seeds its own.
_flow_registry = None


def _default_registry():
    global _flow_registry
    if _flow_registry is None:
        from ..flow import FlowRegistry, default_store_dir
        # persistent named-flow store (single truth across CLI invocations)
        _flow_registry = FlowRegistry.from_default(store_dir=default_store_dir())
    return _flow_registry


def _reset_flow_registry() -> None:
    """Drop the cached registry (used by tests to isolate flow mutations)."""
    global _flow_registry
    _flow_registry = None


@_flow_app.command("list")
def flow_list(
    json_out: bool = typer.Option(False, "--json", help="machine-readable JSON"),
) -> None:
    """List named flows in the registry (builtin + designed + loaded)."""
    from ..flow import FlowRegistry

    reg = _default_registry()
    if json_out:
        _emit_json({"flows": [e.to_dict() for e in reg.list()]})
        return
    entries = reg.list()
    if not entries:
        _ok("no flows registered", markup=False)
        return
    table = Table(title="flow registry", show_header=True)
    for col in ("version", "name", "source", "nodes"):
        table.add_column(col)
    for e in entries:
        table.add_row(str(e.version), e.name, e.source, str(len(e.sm.flow.nodes)))
    console.print(table)
    console.print(f"[dim]{len(entries)} flows[/dim]")


@_flow_app.command("validate")
def flow_validate(
    regime: Path = typer.Argument(..., help="path to a regime.json file"),
    deep: bool = typer.Option(
        True, "--deep/--no-deep", help="run semantic deep checks; ON by default"),
    skills_dir: Optional[Path] = typer.Option(
        None, "--skills-dir", help="path to workflow-regime skills dir"),
    watch: bool = typer.Option(
        False, "--watch", help="re-validate on file change (edit-while-validate)"),
    json_out: bool = typer.Option(False, "--json", help="machine-readable JSON"),
) -> None:
    """Hot-validate a flow file (F2): compile + structural + deep checks.

    `--watch` polls the file and re-runs validation on every change, printing
    ok/err — the "edit-while-validate" loop. No registry mutation.
    """
    from ..flow import validate_sm, compile_spec
    from ..core.state_machine import StateMachineError

    def _once() -> dict:
        try:
            raw = regime.read_text(encoding="utf-8")
            sm = compile_spec(_name_from(raw) or "flow", raw)
            res = validate_sm(sm, skills_dir=skills_dir) if deep else None
            return {"ok": res.ok if res is not None else True,
                    "flow": sm.flow_name, "nodes": len(sm.flow.nodes),
                    "errors": res.errors if res else [],
                    "warnings": res.warnings if res else []}
        except Exception as exc:
            return {"ok": False, "error": str(exc), "errors": [str(exc)],
                    "warnings": []}

    if not watch:
        data = _once()
        if json_out:
            _emit_json(data)
            if not data["ok"]:
                raise typer.Exit(1)
            return
        if data["ok"]:
            _ok(f"flow '{data['flow']}' valid ({data['nodes']} nodes)", markup=False)
        else:
            _fail("; ".join(data.get("errors") or [data.get("error", "invalid")]))
        return

    # --watch: poll mtime, re-validate on change
    import os
    import time as _time

    last = 0.0
    while True:
        try:
            mtime = os.path.getmtime(regime)
        except FileNotFoundError:
            mtime = -1
        if mtime != last:
            last = mtime
            data = _once()
            stamp = _time.strftime("%H:%M:%S")
            if data["ok"]:
                _ok(f"[{stamp}] flow '{data['flow']}' valid "
                    f"({data['nodes']} nodes)", markup=False)
            else:
                # watch mode must NOT raise (a temporarily-invalid edit is the
                # normal editing state); print errors and keep polling until
                # Ctrl-C. `_fail` would exit(1) and break the loop.
                for e in data.get("errors") or []:
                    console.print(Text(f"✗ [{stamp}] {e}", style="bold red"))
                console.print(f"[dim][{stamp}] {regime} invalid, "
                              "keep editing… (Ctrl-C to quit)[/dim]")
        _time.sleep(1.0)


def _name_from(raw: str) -> str | None:
    """Best-effort: the flow name from a regime JSON body (for display)."""
    import json as _json
    try:
        spec = _json.loads(raw)
        if isinstance(spec, dict) and "entry" in spec:
            return spec["entry"].get("flow")
    except Exception:
        pass
    return None


@_flow_app.command("design")
def flow_design(
    name: str = typer.Argument(..., help="flow name to register under"),
    spec: str = typer.Argument(..., help="inline flow spec: full regime JSON or "
                                          "compact {\"entry\":\"a\",\"nodes\":[...]}"),
    skills_dir: Optional[Path] = typer.Option(
        None, "--skills-dir", help="path to workflow-regime skills dir"),
    preflight: bool = typer.Option(
        False, "--preflight", help="also run an offline preflight trial"),
    preflight_fault: str = typer.Option(
        None, "--preflight-fault", help="inject a preflight fault (stall|delay)"),
    json_out: bool = typer.Option(False, "--json", help="machine-readable JSON"),
    perm: str = typer.Option("run", "--perm", help="held permission level"),
) -> None:
    """Design + register a new flow from an inline spec (no file needed).

    Compiles the spec (full regime JSON or compact flow spec) via the unified
    ``compile_spec`` entry, runs the F9 deep gate, and registers it into the
    persistent FlowRegistry — the same design path the god dialog B-route uses,
    exposed for the A-route god / CLI without requiring file-system write access.
    """
    _gate(perm, ["flow", "design", name])
    from ..flow import FlowError, compile_spec

    reg = _default_registry()
    try:
        sm = compile_spec(name, spec)
        if preflight:
            from ..app.preflight import preflight as _preflight
            res = _preflight(sm, timeout_sec=30.0, fault=preflight_fault)
            if not res["ok"]:
                raise FlowError(f"preflight FAILED: outcome={res['outcome']} "
                                f"detail={res['detail']}")
        # register AFTER preflight so a failed gate never mutates the registry
        entry = reg.register(name, sm, source="design",
                             validate=True, file=None,
                             skills_dir=skills_dir)
    except FlowError as exc:
        if json_out:
            _emit_json({"ok": False, "error": str(exc)})
            raise typer.Exit(1)
        _fail(f"design FAILED: {exc}")
    if json_out:
        _emit_json({"ok": True, **entry.to_dict()})
        return
    path = " → ".join(entry.sm.flow_path()) or "(empty)"
    _ok(f"designed flow [bold]{entry.name}[/bold] (v{entry.version}, "
        f"{len(entry.sm.flow.nodes)} nodes, path: {path})", markup=True)


@_flow_app.command("load")
def flow_load(
    regime: Path = typer.Argument(..., help="path to a regime.json file"),
    name: str = typer.Option(None, "--name", help="register under this flow name"),
    skills_dir: Optional[Path] = typer.Option(
        None, "--skills-dir", help="path to workflow-regime skills dir"),
    preflight: bool = typer.Option(
        False, "--preflight", help="also run an offline preflight trial"),
    json_out: bool = typer.Option(False, "--json", help="machine-readable JSON"),
    perm: str = typer.Option("run", "--perm", help="held permission level"),
) -> None:
    """Load + deep-validate + register a flow file into the registry (F4/F9)."""
    _gate(perm, ["flow", "load"])
    from ..flow import FlowRegistry, FlowError

    reg = _default_registry()
    try:
        entry = reg.load(regime, name=name, skills_dir=skills_dir,
                         preflight=preflight)
    except FlowError as exc:
        if json_out:
            _emit_json({"ok": False, "error": str(exc)})
            raise typer.Exit(1)
        _fail(f"load FAILED: {exc}")
    if json_out:
        _emit_json({"ok": True, **entry.to_dict()})
        return
    _ok(f"loaded flow [bold]{entry.name}[/bold] (v{entry.version}, "
        f"{len(entry.sm.flow.nodes)} nodes, source={entry.source})", markup=True)


@_flow_app.command("reload")
def flow_reload(
    name: str = typer.Argument(..., help="flow name to reload"),
    skills_dir: Optional[Path] = typer.Option(
        None, "--skills-dir", help="path to workflow-regime skills dir"),
    preflight: bool = typer.Option(
        False, "--preflight", help="also run an offline preflight trial"),
    json_out: bool = typer.Option(False, "--json", help="machine-readable JSON"),
    perm: str = typer.Option("run", "--perm", help="held permission level"),
) -> None:
    """Atomically hot-reload a file-backed flow (F5/F10). Running workflows keep
    their old StateMachine snapshot; the registry swaps to the new version."""
    _gate(perm, ["flow", "reload"])
    from ..flow import FlowError

    reg = _default_registry()
    try:
        entry = reg.reload(name, skills_dir=skills_dir, preflight=preflight)
    except FlowError as exc:
        if json_out:
            _emit_json({"ok": False, "error": str(exc)})
            raise typer.Exit(1)
        _fail(f"reload FAILED: {exc}")
    if json_out:
        _emit_json({"ok": True, **entry.to_dict()})
        return
    _ok(f"hot-reloaded flow [bold]{entry.name}[/bold] → v{entry.version} "
        f"(running workflows keep old snapshot)", markup=True)


@_flow_app.command("rm")
def flow_rm(
    name: str = typer.Argument(..., help="flow name to remove"),
    json_out: bool = typer.Option(False, "--json", help="machine-readable JSON"),
    perm: str = typer.Option("run", "--perm", help="held permission level"),
) -> None:
    """Remove a named flow from the registry (running workflows unaffected)."""
    _gate(perm, ["flow", "rm"])
    reg = _default_registry()
    if not reg.remove(name):
        if json_out:
            _emit_json({"ok": False, "error": f"unknown flow '{name}'"})
            raise typer.Exit(1)
        _fail(f"unknown flow: {name}")
    if json_out:
        _emit_json({"ok": True, "removed": name})
        return
    _ok(f"removed flow [bold]{name}[/bold]", markup=True)


@_flow_app.command("inspect")
def flow_inspect(
    name: str = typer.Argument(..., help="flow name"),
    json_out: bool = typer.Option(False, "--json", help="machine-readable JSON"),
) -> None:
    """Show a named flow's descriptor summary (nodes + path)."""
    reg = _default_registry()
    entry = reg.get(name)
    if entry is None:
        if json_out:
            _emit_json({"ok": False, "error": f"unknown flow '{name}'"})
            raise typer.Exit(1)
        _fail(f"unknown flow: {name}")
    d = entry.to_dict()
    if json_out:
        _emit_json(d)
        return
    table = Table(title=f"flow {name}", show_header=False)
    table.add_column("key", style="bold cyan")
    table.add_column("value")
    table.add_row("version", str(d["version"]))
    table.add_row("source", d["source"])
    table.add_row("nodes", str(d["nodes"]))
    table.add_row("path", " → ".join(d["path"] or ["(cycle)"]))
    console.print(table)


app.add_typer(_flow_app, name="flow")


# ---------------------------------------------------------------------------
# worker (subcommands: list / up / down / base) — multi opencode instance pool
# ---------------------------------------------------------------------------
_worker_app = typer.Typer(
    help="Worker instance pool (one opencode instance per workspace).")


@_worker_app.command("list")
def worker_list(
    json_out: bool = typer.Option(False, "--json", help="machine-readable JSON"),
) -> None:
    """List worker instances (one per workspace)."""
    from ..worker import WorkerPool

    instances = WorkerPool().list()
    if json_out:
        _emit_json({"instances": [i.to_dict() for i in instances]})
        return
    if not instances:
        _ok("no per-workspace worker instances (use `regime worker up <ws>`)", markup=False)
        return
    table = Table(title="worker instances", show_header=True)
    for col in ("workspace", "container", "port", "healthy"):
        table.add_column(col)
    for i in instances:
        style = "green" if i.healthy else "bold red"
        table.add_row(i.workspace, i.container, str(i.port),
                      Text("yes" if i.healthy else "no", style=style))
    console.print(table)


@_worker_app.command("up")
def worker_up(
    workspace: str = typer.Argument(..., help="workspace id"),
    json_out: bool = typer.Option(False, "--json", help="machine-readable JSON"),
) -> None:
    """Ensure an opencode instance for a workspace (reuse if exists, no duplicate)."""
    from ..worker import WorkerPool

    instance = WorkerPool().ensure(workspace)
    if json_out:
        _emit_json(instance.to_dict())
        return
    _ok(f"workspace '{workspace}' instance ready: {instance.base_url} "
        f"(container={instance.container})", markup=False)


@_worker_app.command("base")
def worker_base(
    workspace: str = typer.Argument(..., help="workspace id"),
) -> None:
    """Print the base URL of a workspace's instance (or exit 1 if absent)."""
    from ..worker import WorkerPool

    instance = WorkerPool().get(workspace)
    if instance is None:
        _fail(f"no instance for workspace '{workspace}' (run `regime worker up {workspace}`)")
    console.print(instance.base_url)


@_worker_app.command("down")
def worker_down(
    workspace: str = typer.Argument(..., help="workspace id"),
) -> None:
    """Stop and remove a workspace's worker instance."""
    from ..worker import WorkerPool

    if WorkerPool().remove(workspace):
        _ok(f"removed workspace '{workspace}' instance", markup=False)
    else:
        _fail(f"no instance for workspace '{workspace}'")


@_worker_app.command("prune")
def worker_prune(
    dry_run: bool = typer.Option(
        False, "--dry-run", help="report idle instances without removing them"),
    max_instances: int = typer.Option(
        None, "--max-instances", help="hard cap on concurrent instances (for up)"),
    json_out: bool = typer.Option(False, "--json", help="machine-readable JSON"),
) -> None:
    """Reclaim idle worker instances (no sessions) to bound fleet resource growth.

    Also accepts --max-instances to set the fleet cap enforced by `worker up`.
    """
    from ..worker import WorkerPool

    pool = WorkerPool(max_instances=max_instances)
    reclaimed = pool.gc_idle(dry_run=dry_run)
    if json_out:
        _emit_json({"reclaimed": reclaimed, "dry_run": dry_run,
                    "cap": max_instances})
        return
    if dry_run:
        _ok(f"idle instances to reclaim: {reclaimed or '(none)'}", markup=False)
    else:
        _ok(f"reclaimed {len(reclaimed)} idle instance(s): {reclaimed or '(none)'}",
            markup=False)
        if max_instances is not None:
            _ok(f"fleet instance cap set to {max_instances}", markup=False)


app.add_typer(_worker_app, name="worker")


# ---------------------------------------------------------------------------
# chaos (fault injection + recovery verification)
# ---------------------------------------------------------------------------
_chaos_app = typer.Typer(
    help="Chaos: inject faults into worker instances and verify recovery.")


@_chaos_app.command("list")
def chaos_list(json_out: bool = typer.Option(False, "--json")) -> None:
    """List available chaos scenarios."""
    from ..chaos import FaultInjector

    if json_out:
        _emit_json({"scenarios": list(FaultInjector.SCENARIOS)})
        return
    _ok("scenarios: " + ", ".join(FaultInjector.SCENARIOS), markup=False)


@_chaos_app.command("inject")
def chaos_inject(
    fault: str = typer.Argument(..., help="kill | stop | start | restart"),
    workspace: str = typer.Argument(..., help="workspace id"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Inject a single fault / recovery action on a workspace instance."""
    from ..chaos import FaultInjector

    inj = FaultInjector()
    if fault == "kill":
        res = inj.kill(workspace)
    elif fault == "stop":
        res = inj.stop(workspace)
    elif fault == "start":
        res = inj.start(workspace)
    elif fault == "restart":
        res = inj.restart(workspace)
    else:
        _fail(f"unknown fault '{fault}' (kill|stop|start|restart)")
    if json_out:
        _emit_json(res.to_dict())
        return
    (console.print("✓", style="bold green") if res.ok else console.print("✗", style="bold red"))
    console.print(f"  {res.fault} {res.workspace}: {res.detail or 'ok'}")


@_chaos_app.command("scenario")
def chaos_scenario(
    scenario: str = typer.Argument(..., help="scenario name (worker-crash-recovery)"),
    workspace: str = typer.Argument(..., help="workspace id (must already exist)"),
    json_out: bool = typer.Option(False, "--json"),
) -> None:
    """Run a recovery scenario: inject fault, observe, recover, verify healthy."""
    from ..chaos import FaultInjector

    inj = FaultInjector()
    log = inj.run_scenario(scenario, workspace)
    ok = all(l.ok for l in log)
    if json_out:
        _emit_json({"scenario": scenario, "workspace": workspace,
                    "ok": ok, "log": [l.to_dict() for l in log]})
        if not ok:
            raise typer.Exit(1)
        return
    for l in log:
        mark = "✓" if l.ok else "✗"
        console.print(f"  {mark} {l.fault} {l.workspace} {l.detail or ''}")
    if ok:
        _ok(f"scenario '{scenario}' passed (worker recovered)", markup=False)
    else:
        _fail(f"scenario '{scenario}' failed (worker did not recover)")


app.add_typer(_chaos_app, name="chaos")


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