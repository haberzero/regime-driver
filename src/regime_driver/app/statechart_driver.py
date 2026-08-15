"""Statechart-network orchestration (app layer).

This is the top-level entry. It assembles a Runtime with:

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
from ..infra.drive_client import DriveClient
from ..infra.settings import Settings
from .watchdog_policy import WatchdogPolicy
from .watchdog_unit import WatchdogUnit
from .statechart_runtime import Runtime, ThreadedUnit
from .workflow_unit import WorkflowUnit


class StatechartDriver:
    """Assembly: Runtime + WorkflowUnit + WatchdogUnit (+ optional override)."""

    def __init__(
        self,
        settings: Settings,
        state_machine: StateMachine,
        client: DriveClient,
        ledger: Ledger | None = None,
        reporter: "Reporter | None" = None,
        roles: RoleRegistry | None = None,
        watchdog: ThreadedUnit | None = None,
        enforce_invariants: bool = True,
        global_deadline_sec: float | None = None,
        max_global_nodes: int | None = None,
        heartbeat_stale_sec: float | None = None,
        run_id: str | None = None,
        sse: "SseActivity | None" = None,
        regime: "Regime | None" = None,
        hooks: "HookRegistry | None" = None,
    ) -> None:
        """Assemble the runtime.

        A `Regime` (the whole operating rule) is the authoritative "how to run"
        declaration when given: it supplies the flow, roles, supervision policy
        and handover policy, with its thresholds taking precedence over the
        settings defaults. The legacy positional form (state_machine/roles from
        settings JSON) remains for direct low-level construction.

        `hooks` (unified extension registry) supplies user watchdog rules
        (merged into the policy) and lifecycle hooks (fired by the workflow /
        watchdog units).
        """
        from .watchdog_policy import policy_from_json

        self.settings = settings
        self.client = client
        self.ledger = ledger
        self.reporter = reporter
        self.run_id = run_id or self._gen_run_id()
        self.hooks = hooks
        self.runtime = Runtime(enforce_invariants=enforce_invariants)
        if regime is not None:
            self.sm = regime.flow
            self.roles = regime.roles or roles or default_roles()
            stall_sec = (regime.stall_sec if regime.stall_sec is not None
                         else float(settings.stall_sec))
            auto_resume = (regime.auto_resume_sec if regime.auto_resume_sec is not None
                           else float(settings.auto_resume_sec))
            policy = regime.watchdog or policy_from_json(settings.watchdog_policy_json)
            handover = regime.handover
        else:
            self.sm = state_machine
            self.roles = roles or default_roles()
            stall_sec = float(settings.stall_sec)
            auto_resume = float(settings.auto_resume_sec)
            policy = policy_from_json(settings.watchdog_policy_json)
            handover = None
        # user watchdog rules from the extension registry merge into the
        # policy so one declared rule set drives supervision.
        if self.hooks is not None and self.hooks.rules:
            policy = policy.with_rules(self.hooks.rules) if policy is not None \
                else WatchdogPolicy(rules=list(self.hooks.rules))
        # the watchdog is a programmable policy engine; build the
        # policy from the regime (or settings JSON), else the default.
        self.watchdog = watchdog or WatchdogUnit(
            unit_id="watchdog",
            stall_sec=stall_sec,
            control_dst="workflow",
            bus=self.runtime.bus,
            global_deadline_sec=global_deadline_sec,
            max_global_nodes=max_global_nodes,
            heartbeat_stale_sec=heartbeat_stale_sec,
            policy=policy,
            auto_resume_sec=auto_resume,
            reporter=reporter,
            run_id=self.run_id,
            hooks=self.hooks,
        )
        if self.watchdog.bus is None:
            # a custom watchdog created without a bus: give it the runtime's
            # bus so its send()/emit() work (it manages its own subscriptions).
            self.watchdog.bus = self.runtime.bus
        self.workflow = WorkflowUnit(
            settings, self.sm, client, ledger,
            reporter=reporter, roles=self.roles,
            unit_id="workflow", run_id=self.run_id, bus=self.runtime.bus,
            sse=sse, context_policy=handover, hooks=self.hooks,
        )
        self.runtime.register(self.watchdog)
        self.runtime.register(self.workflow)

    @classmethod
    def from_regime(
        cls,
        regime: "Regime",
        settings: Settings,
        client: DriveClient,
        ledger: Ledger | None = None,
        reporter: "Reporter | None" = None,
        watchdog: ThreadedUnit | None = None,
        enforce_invariants: bool = True,
        global_deadline_sec: float | None = None,
        max_global_nodes: int | None = None,
        heartbeat_stale_sec: float | None = None,
        run_id: str | None = None,
        sse: "SseActivity | None" = None,
        hooks: "HookRegistry | None" = None,
    ) -> "StatechartDriver":
        """One-shot assembly from a whole operating rule (regime first-class)."""
        return cls(
            settings, regime.flow, client, ledger, reporter,
            roles=regime.roles, watchdog=watchdog,
            enforce_invariants=enforce_invariants,
            global_deadline_sec=global_deadline_sec,
            max_global_nodes=max_global_nodes,
            heartbeat_stale_sec=heartbeat_stale_sec,
            run_id=run_id, sse=sse, regime=regime, hooks=hooks,
        )

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
                    # Timeout must be recorded like any other outcome: the
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