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
) -> None:
    """Run a task through the regime flow on a developer session."""
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
    _run(settings, context, title, json_out=json_out)


def _run(settings: Settings, context: str, title: str, json_out: bool = False) -> None:
    try:
        sm = load_regime(settings.regime_path)
    except (StateMachineError, FileNotFoundError) as exc:
        _fail(f"error loading regime: {exc}")

    client = OpenCodeClient(settings.base_url, model=settings.model,
                            timeout=settings.request_timeout)
    ledger = Ledger(settings.ledger_path) if settings.ledger_path else None
    driver = StatechartDriver(settings, sm, client, ledger)

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
) -> None:
    """Run several tasks as concurrent workflows on one worker."""
    from ..app.statechart_cluster import StatechartCluster

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
    try:
        sm = load_regime(settings.regime_path)
    except (StateMachineError, FileNotFoundError) as exc:
        _fail(f"error loading regime: {exc}")

    client = OpenCodeClient(settings.base_url, model=settings.model,
                            timeout=settings.request_timeout)
    cluster = StatechartCluster(client)
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


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------
@app.command("validate")
def validate(
    regime: Optional[Path] = typer.Option(
        None, "--regime", help="path to regime.json (default: packaged descriptor)"
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
    if json_out:
        _emit_json({
            "ok": True, "flow": sm.flow_name, "nodes": len(sm.flow.nodes),
            "path": path, "flows": flows, "unreachable": dead,
        })
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
) -> None:
    """List all opencode sessions on the worker with their live status."""
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

    run_dialog(base, model, live=live, print_fn=lambda s: console.print(s))


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
) -> None:
    """Send a message to a specific opencode session (independent interaction)."""
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
            try:
                console.print(line)  # already JSON
            except Exception:
                console.print(line)

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