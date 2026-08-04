"""regime-driver CLI (typer + rich)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .. import __version__
from ..core.contract import gate_reviewer_verdict, parse_reviewer_verdict
from ..core.state_machine import StateMachineError
from ..infra.config import load_settings
from ..infra.ledger import Ledger
from ..infra.opencode import OpenCodeClient
from ..infra.regime_loader import load_regime
from ..infra.settings import Settings
from ..app.driver import RegimeDriver

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
) -> None:
    """Run a task through the regime flow on a developer session."""
    settings = load_settings(
        config_file=config,
        overrides={
            "base_url": base,
            "regime_path": str(regime) if regime else None,
            "ledger_path": str(ledger) if ledger else None,
            "default_deadline_sec": deadline,
        },
    )
    _run(settings, context, title)


def _run(settings: Settings, context: str, title: str) -> None:
    try:
        sm = load_regime(settings.regime_path)
    except (StateMachineError, FileNotFoundError) as exc:
        _fail(f"error loading regime: {exc}")

    client = OpenCodeClient(settings.base_url)
    ledger = Ledger(settings.ledger_path) if settings.ledger_path else None
    with console.status(f"[cyan]running flow[/cyan] [bold]{sm.flow_name}[/bold] …"):
        try:
            driver = RegimeDriver(settings, sm, client, ledger)
            result = driver.run(context, title)
        finally:
            if ledger:
                ledger.close()

    if result.outcome == "complete":
        _ok(f"flow completed at node [bold]{result.end_node}[/bold]", markup=True)
    else:
        _fail(f"flow {result.outcome} at node [bold]{result.end_node}[/bold]"
              + (f": {result.detail}" if result.detail else ""), markup=True)
    if result.report:
        console.print(Panel(Text(result.report), title="final report", border_style="cyan"))


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
    base: str = typer.Option("http://127.0.0.1:4097", "--base", help="worker URL"),
) -> None:
    """Check worker health."""
    client = OpenCodeClient(base)
    healthy = client.health()
    if healthy:
        _ok(f"worker healthy at [bold]{base}[/bold]", markup=True)
    else:
        _fail(f"worker unhealthy at {base}")


if __name__ == "__main__":
    app()