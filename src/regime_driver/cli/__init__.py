"""regime-driver CLI (typer + rich)."""

from __future__ import annotations

import json
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
    _run(settings, context, title)


def _run(settings: Settings, context: str, title: str) -> None:
    try:
        sm = load_regime(settings.regime_path)
    except (StateMachineError, FileNotFoundError) as exc:
        _fail(f"error loading regime: {exc}")

    client = OpenCodeClient(settings.base_url, model=settings.model,
                            timeout=settings.request_timeout)
    ledger = Ledger(settings.ledger_path) if settings.ledger_path else None
    with console.status(f"[cyan]running flow[/cyan] [bold]{sm.flow_name}[/bold] …"):
        try:
            driver = StatechartDriver(settings, sm, client, ledger)
            outcome, end_node, detail = driver.run(context, title)
        finally:
            if ledger:
                ledger.close()

    if outcome == Outcome.COMPLETE:
        _ok(f"flow completed at node [bold]{end_node}[/bold]", markup=True)
    else:
        _fail(f"flow {outcome.value} at node [bold]{end_node}[/bold]"
              + (f": {detail}" if detail else ""), markup=True)


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------
@app.command("validate")
def validate(
    regime: Optional[Path] = typer.Option(
        None, "--regime", help="path to regime.json (default: packaged descriptor)"
    ),
) -> None:
    """Validate a regime.json state machine descriptor."""
    try:
        sm = load_regime(regime)
        path = sm.flow_path()
    except (StateMachineError, FileNotFoundError) as exc:
        _fail(f"INVALID: {exc}")

    table = Table(title="regime descriptor", show_header=False)
    table.add_column("key", style="bold cyan")
    table.add_column("value")
    table.add_row("flow", sm.flow_name)
    table.add_row("nodes", str(len(sm.flow.nodes)))
    table.add_row("path length", str(len(path)))
    table.add_row("path", " → ".join(path))
    console.print(table)
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
) -> None:
    """Check worker health."""
    client = OpenCodeClient(base)
    healthy = client.health()
    if healthy:
        _ok(f"worker healthy at [bold]{base}[/bold]", markup=True)
    else:
        _fail(f"worker unhealthy at {base}")


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
    """Open the God Dialog: one natural-language control/monitor surface."""
    from ..app.god_dialog import GodDialogUnit
    from ..app.statechart_cluster import StatechartCluster
    from ..infra.opencode import OpenCodeClient
    from ..infra.regime_loader import load_regime
    from ..testing import MockClient

    settings = load_settings(overrides={"base_url": base, "model": model})
    sm = load_regime()
    if live:
        client = OpenCodeClient(base, model=model, timeout=settings.request_timeout)
        llm = _make_dialog_llm(base, model, settings.request_timeout)
    else:
        client = MockClient(sm=sm)
        llm = None

    cluster = StatechartCluster(client)
    god = cluster.register_unit(GodDialogUnit(
        bus=cluster.runtime.bus, llm=llm,
        settings_render=lambda: settings.model_dump().__str__()))

    def launcher(ctx, title):
        wid = f"god-{len(cluster.workflows) + 1}"
        cluster.add_workflow(wid, settings, sm)
        cluster.start()
        cluster.submit(wid, ctx, title)
        return {"workflow_id": wid}

    god.launcher = launcher
    cluster.start()

    console.print("[bold]=== 上帝对话框 (God Dialog) ===[/bold]")
    console.print("唯一对话面：用自然语言控制/监控所有 workflow。输入 help 看命令。")
    try:
        while True:
            try:
                line = input("God> ")
            except (EOFError, KeyboardInterrupt):
                console.print("\n再见。")
                break
            if not line.strip():
                continue
            out = god.command(line)
            if out == "__exit__":
                break
            console.print(out)
            for r in god.drain_replies():
                console.print(f"[dim][async][/dim] {r}")
    finally:
        cluster.stop()


def _make_dialog_llm(base: str, model: str, timeout: float):
    """Worker-thread LLM runner for the dialog's free-form explain."""
    import time as _t
    client = OpenCodeClient(base, model=model, timeout=timeout)

    def run(text, context):
        sid = client.create_session("god-dialog-explain")
        prompt = (
            "你是制度流程机器人的上帝对话框，负责向用户解释系统状态。\n"
            f"用户问题：{text}\n\n当前系统状态快照：\n{context}\n\n"
            "请用简洁中文回答，说明要点并给出下一步建议。"
        )
        client.send_message(sid, prompt, "developer")
        dl = _t.time() + timeout
        while _t.time() < dl:
            msgs = client.read_messages(sid)
            for m in reversed(msgs):
                if getattr(m, "role", None) == "assistant" and (m.reply or m.text).strip():
                    return (m.reply or m.text).strip()
            _t.sleep(1)
        return "(LLM 超时)"

    return run


if __name__ == "__main__":
    app()