"""Offline preflight trial run (WORK_PLAN4 I2).

Runs the exact same StatechartDriver / WorkflowUnit code against a MockClient
to answer: **does this flow actually terminate cleanly offline?** This is the
"trial detection" that static checks cannot provide — it surfaces semantic
errors (a reviewer gate that can never advance, a flow with no terminal, a
node whose role cannot be served) before touching a real worker/session.

A clean flow yields COMPLETE quickly. `fault` optionally injects a developer
stall (to confirm the watchdog backstop) or a reviewer delay (timing).
"""

from __future__ import annotations

from ..core.models import NodeType, Outcome
from ..infra.regime_loader import load_regime
from ..infra.settings import Settings
from ..testing import MockClient
from .statechart_driver import StatechartDriver


def _reviewer_gate_node(sm) -> str:
    """Pick a judge/reviewer-role node to fault-inject (defaults to entry start)."""
    for nid, node in sm.flow.nodes.items():
        if node.type == NodeType.JUDGE or node.role == "reviewer":
            return nid
    return sm.start


def preflight(
    sm=None,
    *,
    fault: str | None = None,
    timeout_sec: float = 30.0,
) -> dict:
    """Offline trial run; returns a machine-readable preflight result dict."""
    sm = sm if sm is not None else load_regime()
    client = MockClient(sm=sm)
    start_node = getattr(sm, "start", None)
    if fault == "stall" and start_node:
        client.rule(sm.node(start_node).role, start_node, stall=True)
    elif fault == "delay":
        # derive the reviewer gate node from the flow (any judge/reviewer-role node),
        # so the fault applies to an arbitrary user flow, not just `code_workflow`.
        gate = _reviewer_gate_node(sm)
        client.rule("reviewer", gate, delay=0.3)
    elif fault is not None:
        return {"ok": False, "outcome": "error", "detail": f"unknown fault '{fault}'"}

    settings = Settings(monitor_enabled=False, poll_sec=0.1, stall_sec=5)
    driver = StatechartDriver(settings, sm, client, enforce_invariants=True)
    try:
        outcome, end, detail = driver.run("preflight trial", timeout_sec=timeout_sec)
    except Exception as exc:  # noqa: BLE001 - surface any driver error as a failed trial
        return {"ok": False, "outcome": "error", "end": None, "detail": str(exc)}
    ok = outcome == Outcome.COMPLETE
    return {"ok": ok, "outcome": outcome.value, "end": end, "detail": detail}
