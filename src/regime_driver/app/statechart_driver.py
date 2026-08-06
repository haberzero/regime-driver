"""Statechart-network orchestration (app layer, final refactor).

This is the top-level entry that replaces the old `RegimeDriver`'s inline
monitor integration. It assembles a Runtime with:

  * a WorkflowUnit (governed) that drives the regime flow via a single-threaded
    mixed loop, reporting its alive session state to the constitution;
  * a ConstitutionUnit (watchdog) that detects stalls/dead-loops from those
    REPORT signals and broadcasts STOP to interrupt the workflow.

The Runtime enforces the root invariants (at least one watchdog, an
inextinguishable STOP channel, meta-iteration bound) before starting. A user may
supply their own constitution unit in place of the built-in one.
"""

from __future__ import annotations

from ..core.role import RoleRegistry, default_roles
from ..core.state_machine import StateMachine
from ..infra.ledger import Ledger
from ..infra.opencode import OpenCodeClient
from ..infra.settings import Settings
from .constitution_unit import ConstitutionUnit
from .statechart_runtime import Runtime, ThreadedUnit
from .workflow_unit import WorkflowUnit


class StatechartDriver:
    """Assembly: Runtime + WorkflowUnit + ConstitutionUnit (+ optional override)."""

    def __init__(
        self,
        settings: Settings,
        state_machine: StateMachine,
        client: OpenCodeClient,
        ledger: Ledger | None = None,
        roles: RoleRegistry | None = None,
        constitution: ThreadedUnit | None = None,
        enforce_invariants: bool = True,
    ) -> None:
        self.settings = settings
        self.sm = state_machine
        self.client = client
        self.ledger = ledger
        self.roles = roles or default_roles()
        self.runtime = Runtime(enforce_invariants=enforce_invariants)
        self.constitution = constitution or ConstitutionUnit(
            unit_id="constitution",
            stall_sec=float(settings.stall_sec),
            control_dst="workflow",
            bus=self.runtime.bus,
        )
        if self.constitution.bus is None:
            self.constitution.bus = self.runtime.bus
        self.workflow = WorkflowUnit(
            settings, state_machine, client, ledger, self.roles,
            unit_id="workflow", bus=self.runtime.bus,
        )
        self.runtime.register(self.constitution)
        self.runtime.register(self.workflow)

    def run(self, context: str, title: str = "regime-workflow") -> tuple:
        """Run the flow to completion on the runtime; return (outcome, end, detail)."""
        self.runtime.start()
        try:
            self.workflow.submit(context, title)
            while self.workflow.result() is None:
                import time
                time.sleep(0.05)
            return self.workflow.result()
        finally:
            self.runtime.stop()