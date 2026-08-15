"""Offline preflight trial run.

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


def _scale_timeout(node_count: int) -> float:
    """Offline trial duration scales with flow size.

    MockClient trial costs ~8s per node (polling + per-node turns); a fixed
    30s cap silently fails long flows (10+ nodes), so the default timeout
    grows with the node count while keeping a 30s floor for small flows.
    """
    return max(30.0, 8.0 * node_count)


def preflight(
    sm=None,
    *,
    fault: str | None = None,
    timeout_sec: float | None = None,
    stall_sec: float = 5.0,
) -> dict:
    """Offline trial run; returns a machine-readable preflight result dict.

    ``stall_sec`` controls how long a stall-fault run must be frozen before the
    watchdog escalates; the production default is 5s (fast enough for a trial),
    tests may pass a smaller value to speed up fault-path verification.

    ``timeout_sec`` defaults to a node-count-scaled budget (``_scale_timeout``)
    so arbitrarily long flows still get a full offline trial.
    """
    sm = sm if sm is not None else load_regime()
    if timeout_sec is None:
        timeout_sec = _scale_timeout(len(sm.flow.nodes))
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

    settings = Settings(monitor_enabled=False, poll_sec=0.1, stall_sec=stall_sec,
                        verify_enabled=False)
    driver = StatechartDriver(settings, sm, client, enforce_invariants=True)
    try:
        outcome, end, detail = driver.run("preflight trial", timeout_sec=timeout_sec)
        # best-effort recovery: a wall-clock expiry of the trial (not a flow
        # failure) is retried once with a doubled budget before giving up —
        # the trial is offline/cheap, and a genuine timeout is often just a
        # poll-boundary artifact on a long flow.
        if (outcome == Outcome.ERROR and (detail or "").startswith("run timed out")
                and not fault):
            outcome, end, detail = driver.run(
                "preflight trial (retry)", timeout_sec=timeout_sec * 2)
    except Exception as exc:  # noqa: BLE001 - surface any driver error as a failed trial
        return {"ok": False, "outcome": "error", "end": None, "detail": str(exc)}
    ok = outcome == Outcome.COMPLETE
    return {"ok": ok, "outcome": outcome.value, "end": end, "detail": detail}
