"""Multi-workflow concurrent orchestration (app layer).

Runs several WorkflowUnits in parallel on one Runtime, sharing a single
ConstitutionUnit (watchdog) and a shared blackboard. Each workflow is isolated on
the blackboard by its own id and drives its own task; the constitution stops only
the offending workflow (point-to-point), so one stalled run does not kill the
others. This is the "peer state machines, no hierarchy" model applied to many
concurrent runs.
"""

from __future__ import annotations

import time

from ..core.role import RoleRegistry, default_roles
from ..core.state_machine import StateMachine
from ..infra.ledger import Ledger
from ..infra.opencode import OpenCodeClient
from ..infra.settings import Settings
from .constitution_unit import ConstitutionUnit
from .statechart_runtime import Runtime, ThreadedUnit
from .workflow_unit import WorkflowUnit


class StatechartCluster:
    """A Runtime hosting one constitution + many concurrent workflows."""

    def __init__(
        self,
        client: OpenCodeClient,
        ledger: Ledger | None = None,
        constitution: ThreadedUnit | None = None,
        enforce_invariants: bool = True,
        **constitution_kwargs,
    ) -> None:
        self.client = client
        self.ledger = ledger
        self.runtime = Runtime(enforce_invariants=enforce_invariants)
        self.constitution = constitution or ConstitutionUnit(
            unit_id="constitution", control_dst="*", bus=self.runtime.bus,
            **constitution_kwargs,
        )
        if self.constitution.bus is None:
            self.constitution.bus = self.runtime.bus
        self.workflows: dict[str, WorkflowUnit] = {}
        self.runtime.register(self.constitution)

    # -- workflow management -------------------------------------------------

    def add_workflow(
        self,
        workflow_id: str,
        settings: Settings,
        state_machine: StateMachine,
        roles: RoleRegistry | None = None,
    ) -> WorkflowUnit:
        """Register a workflow unit under a unique id."""
        if workflow_id in self.workflows:
            raise ValueError(f"workflow id '{workflow_id}' already registered")
        wf = WorkflowUnit(
            settings, state_machine, self.client, self.ledger,
            roles=roles or default_roles(),
            unit_id=workflow_id, bus=self.runtime.bus,
        )
        self.runtime.register(wf)
        self.workflows[workflow_id] = wf
        return wf

    # -- lifecycle -----------------------------------------------------------

    def register_unit(self, unit: ThreadedUnit) -> ThreadedUnit:
        """Join a peer unit (e.g. GodDialogUnit) onto this cluster's runtime so
        it shares the same bus/blackboard and observes the workflows live."""
        self.runtime.register(unit)
        return unit

    def start(self) -> "StatechartCluster":
        self.runtime.start()
        return self

    def stop(self, timeout: float = 2.0) -> None:
        self.runtime.stop(timeout)

    # -- run -----------------------------------------------------------------

    def submit(self, workflow_id: str, context: str,
               title: str | None = None) -> None:
        self.workflows[workflow_id].submit(context, title or f"regime-{workflow_id}")

    def wait(self, timeout_sec: float | None = None) -> dict:
        """Wait for all workflows to finish; return {id: (outcome,end,detail)}."""
        deadline = time.time() + (timeout_sec or 3600)
        while any(wf.result() is None for wf in self.workflows.values()):
            if time.time() > deadline:
                break
            time.sleep(0.05)
        return {wid: wf.result() for wid, wf in self.workflows.items()}

    def run_all(self, tasks: dict[str, str], timeout_sec: float | None = None) -> dict:
        """Submit a dict {workflow_id: context} and wait for all to finish."""
        self.start()
        try:
            for wid, ctx in tasks.items():
                self.submit(wid, ctx)
            return self.wait(timeout_sec)
        finally:
            self.stop()