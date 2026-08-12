"""One-command self-driving stack: run + supervisor + reporter composed (P0#1).

`regime drive <task>` brings up the entire self-driving stack with a single
command, instead of separately invoking `regime run`, `regime supervisor` and a
reporter:

  * the **workflow executor** (StatechartDriver) drives the regime flow on the
    worker;
  * the **process-external supervisor** (independent clock) watches worker
    health (T1/L4), session stall (T2), deadline and the correction ladder;
  * both share **one Reporter journal** as the single event truth source;

and the whole stack is registered in the supervised-task registry so it is
tracked, stoppable and reportable (`regime task` / `regime report --tasks-dir`).

The supervisor loop terminates as soon as the workflow produces a result (via
``Supervisor.run(stop_when=...)``), so the drive returns promptly on COMPLETE /
BLOCKED / ERROR rather than running to the deadline.

See docs/DESIGN-drive.md.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Callable

from .app.reporter import Reporter
from .app.statechart_driver import StatechartDriver
from .core.models import Outcome
from .infra.ledger import Ledger
from .infra.opencode import OpenCodeClient
from .infra.settings import Settings
from .supervisor import Supervisor


def _ledger_for(settings: Settings) -> Ledger | None:
    """Build a Ledger from settings when a ledger path is configured (None = off)."""
    if not settings.ledger_path:
        return None
    return Ledger(settings.ledger_path)


@dataclass
class DriveResult:
    """The composed outcome of a drive run."""

    outcome: str
    end: str | None = None
    detail: str | None = None
    supervisor: str | None = None
    elapsed_sec: float = 0.0
    session_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "outcome": self.outcome,
            "end": self.end,
            "detail": self.detail,
            "supervisor": self.supervisor,
            "elapsed_sec": self.elapsed_sec,
            "session_id": self.session_id,
        }


class Drive:
    """Compose the workflow executor + process-external supervisor + reporter.

    A single object that owns the executor thread and the supervisor loop so a
    call site (CLI / API) gets a whole self-driving stack from one call.
    """

    def __init__(
        self,
        settings: Settings,
        state_machine,
        client: OpenCodeClient,
        reporter: Reporter | None = None,
        *,
        container: str | None = None,
        deadline_sec: float | None = None,
        stall_sec: float = 60.0,
        health_poll_sec: float = 10.0,
        session_discovery_timeout: float = 60.0,
        meta_enabled: bool = False,
        meta_model: str | None = None,
        prune_max_records: int | None = None,
        prune_max_age: float | None = None,
    ) -> None:
        self.settings = settings
        self.sm = state_machine
        self.client = client
        self.reporter = reporter
        self.container = container
        self.deadline_sec = deadline_sec
        self.stall_sec = stall_sec
        self.health_poll_sec = health_poll_sec
        self.session_discovery_timeout = session_discovery_timeout
        self.meta_enabled = meta_enabled
        self.meta_model = meta_model
        # journal retention: bound the shared journal at drive teardown (both params
        # optional; enabled only when the caller passes at least one).
        self.prune_max_records = prune_max_records
        self.prune_max_age = prune_max_age
        self.driver: StatechartDriver | None = None
        self._session_id: str | None = None
        self._result: dict = {}

    # -- internals ----------------------------------------------------------

    def _discover_session(self) -> str | None:
        """Wait for the workflow to create its anchor (primary) session.

        The workflow creates the anchor session asynchronously on its own
        thread; poll until it exists (bounded), falling back to any created
        session id. Returns None if none appears within the timeout.
        """
        deadline = time.time() + self.session_discovery_timeout
        while self.driver is not None and time.time() < deadline:
            wf = self.driver.workflow
            anchor = getattr(wf, "_anchor", None)
            if anchor:
                st = wf.sessions.get(anchor)
                if st is not None and st.session_id:
                    return st.session_id
            sids = wf.sessions.all_session_ids()
            if sids:
                return sids[0]
            time.sleep(0.5)
        return None

    # -- public -------------------------------------------------------------

    def run(self, context: str, title: str = "regime-workflow") -> DriveResult:
        """Run the full stack: executor thread + supervisor loop, share reporter.

        Returns a DriveResult. The supervisor loop ends when the workflow yields
        a result (stop_when) or the deadline / L5 escalation fires.
        """
        self.driver = StatechartDriver(
            self.settings, self.sm, self.client, reporter=self.reporter,
            ledger=_ledger_for(self.settings),
            global_deadline_sec=self.deadline_sec,
        )
        t0 = time.time()

        def _go() -> None:
            try:
                self._result["res"] = self.driver.run(
                    context, title, timeout_sec=self.settings.max_driver_wait_sec)
            except Exception as exc:  # surface executor failure, don't hang
                self._result["res"] = (Outcome.ERROR, None, f"executor: {exc}")

        t = threading.Thread(target=_go, daemon=True)
        t.start()
        session_id = self._discover_session()
        self._session_id = session_id
        sup = Supervisor(
            self.client, self.reporter, container=self.container,
            stall_sec=self.stall_sec, health_poll_sec=self.health_poll_sec,
            deadline_sec=self.deadline_sec, session_id=session_id, goal=context,
            meta_enabled=self.meta_enabled, meta_model=self.meta_model,
        )
        sup_outcome = sup.run(stop_when=lambda: "res" in self._result)
        t.join(timeout=5)
        if self.driver.ledger is not None:
            self.driver.ledger.close()
        if "res" not in self._result:
            outcome, end, detail = (Outcome.ERROR, None, "drive did not complete")
        else:
            outcome, end, detail = self._result["res"]
        # journal retention: bound the shared journal at teardown so long-run scripts
        # do not grow the journal without limit (best-effort, never fails a run).
        if self.reporter is not None and (
                self.prune_max_records is not None or self.prune_max_age is not None):
            try:
                self.reporter.retain(max_age_sec=self.prune_max_age,
                                     max_records=self.prune_max_records)
            except Exception as exc:  # noqa: BLE001 — prune is best-effort
                # audit the failure (a silent swallow would make retention
                # problems invisible in long-run durability)
                import logging
                logging.getLogger(__name__).warning(
                    "journal prune skipped: %s", exc)
        return DriveResult(
            outcome=outcome.value, end=end, detail=detail,
            supervisor=sup_outcome, elapsed_sec=round(time.time() - t0, 1),
            session_id=session_id,
        )
