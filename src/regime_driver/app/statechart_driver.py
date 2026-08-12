"""Statechart-network orchestration (app layer, final refactor).

This is the top-level entry that replaces the old `RegimeDriver`'s inline
monitor integration. It assembles a Runtime with:

  * a WorkflowUnit (governed) that drives the regime flow via a single-threaded
    mixed loop, reporting its alive session state to the watchdog;
  * a WatchdogUnit (watchdog) that detects stalls/dead-loops from those
    REPORT signals and broadcasts STOP to interrupt the workflow.

The Runtime enforces the root invariants (at least one watchdog, an
inextinguishable STOP channel, meta-iteration bound) before starting. A user may
supply their own watchdog unit in place of the built-in one.
"""

from __future__ import annotations

from ..core.models import Outcome
from ..core.role import RoleRegistry, default_roles
from ..core.state_machine import StateMachine
from ..infra.ledger import Ledger
from ..infra.opencode import OpenCodeClient
from ..infra.settings import Settings
from .watchdog_unit import WatchdogUnit
from .statechart_runtime import Runtime, ThreadedUnit
from .workflow_unit import WorkflowUnit


class StatechartDriver:
    """Assembly: Runtime + WorkflowUnit + WatchdogUnit (+ optional override)."""

    def __init__(
        self,
        settings: Settings,
        state_machine: StateMachine,
        client: OpenCodeClient,
        ledger: Ledger | None = None,
        reporter: "Reporter | None" = None,
        roles: RoleRegistry | None = None,
        watchdog: ThreadedUnit | None = None,
        enforce_invariants: bool = True,
        global_deadline_sec: float | None = None,
        max_global_nodes: int | None = None,
        heartbeat_stale_sec: float | None = None,
        run_id: str | None = None,
    ) -> None:
        self.settings = settings
        self.sm = state_machine
        self.client = client
        self.ledger = ledger
        self.reporter = reporter
        self.roles = roles or default_roles()
        self.run_id = run_id or self._gen_run_id()
        self.runtime = Runtime(enforce_invariants=enforce_invariants)
        self.watchdog = watchdog or WatchdogUnit(
            unit_id="watchdog",
            stall_sec=float(settings.stall_sec),
            control_dst="workflow",
            bus=self.runtime.bus,
            global_deadline_sec=global_deadline_sec,
            max_global_nodes=max_global_nodes,
            heartbeat_stale_sec=heartbeat_stale_sec,
        )
        if self.watchdog.bus is None:
            # a custom watchdog created without a bus: give it the runtime's
            # bus so its send()/emit() work (it manages its own subscriptions).
            self.watchdog.bus = self.runtime.bus
        self.workflow = WorkflowUnit(
            settings, state_machine, client, ledger,
            reporter=reporter, roles=self.roles,
            unit_id="workflow", run_id=self.run_id, bus=self.runtime.bus,
        )
        self.runtime.register(self.watchdog)
        self.runtime.register(self.workflow)

    @staticmethod
    def _gen_run_id() -> str:
        """A stable-per-process unique run id for report-bus attribution."""
        import uuid

        return f"run-{uuid.uuid4().hex[:8]}"

    def run(self, context: str, title: str = "regime-workflow",
            timeout_sec: float | None = None) -> tuple:
        """Run the flow on the runtime; return (outcome, end, detail).

        `timeout_sec` bounds the wait (a safeguard if the workflow thread dies);
        on timeout it returns an ERROR result rather than hanging forever.
        """
        import time
        self.runtime.start()
        try:
            self.workflow.submit(context, title)
            deadline = time.time() + (timeout_sec or self.settings.max_driver_wait_sec)
            while self.workflow.result() is None:
                if time.time() > deadline:
                    # Timeout must be recorded like any other outcome (D1): the
                    # workflow thread never reached a terminal state, so no
                    # outcome event would otherwise be written to ledger/reporter
                    # and the run would vanish from the report bus.
                    self.workflow.record_outcome(
                        Outcome.ERROR.value,
                        node=self.workflow._node,
                        detail="run timed out",
                    )
                    return (Outcome.ERROR, self.workflow._node, "run timed out")
                time.sleep(0.05)
            return self.workflow.result()
        finally:
            self.runtime.stop()