"""Parallel batch driver: physically-isolated self-driving runs in parallel.

The concurrent self-driving vision needs each task to run in its own workspace so
they cannot clobber each other. With the multi-instance WorkerPool (one opencode
instance per workspace, docs/subsystems/02_worker_isolation.md), a batch drives several
full `Drive` stacks IN PARALLEL, each bound to its own workspace instance:

  * each task -> one workspace instance (created/reused via WorkerPool, no duplicate);
  * each task runs a full Drive (executor + process-external supervisor + reporter);
  * all tasks share ONE Reporter journal (single truth, thread-safe; attribution by
    workflow id), so the whole batch reports to one board.

Workspace instances are ensured SEQUENTIALLY first (avoids the free-port
allocation race when launching containers in parallel), then the tasks run in
parallel threads. See docs/subsystems/03_parallel.md.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from .app.reporter import Reporter
from .core.models import Outcome
from .drive import Drive, DriveResult
from .infra.opencode import OpenCodeClient
from .infra.settings import Settings
from .worker import WorkerPool


@dataclass
class ParallelTask:
    """One task in a parallel batch: its context and the workspace it runs in."""

    task_id: str
    context: str
    workspace: str


class Parallel:
    """Run many isolated full-stack drives in parallel, one per workspace."""

    def __init__(
        self,
        settings: Settings,
        state_machine,
        reporter: Reporter | None = None,
        *,
        pool: WorkerPool | None = None,
        deadline_sec: float | None = None,
        meta_enabled: bool = False,
        meta_model: str | None = None,
    ) -> None:
        self.settings = settings
        self.sm = state_machine
        self.reporter = reporter
        self.pool = pool or WorkerPool()
        self.deadline_sec = deadline_sec
        self.meta_enabled = meta_enabled
        self.meta_model = meta_model

    # -- instance provisioning (sequential, avoids port-allocation race) ------

    def _ensure_instances(self, workspaces: list[str]) -> dict[str, str]:
        """Ensure every workspace instance (sequential) -> {ws: base_url}."""
        out = {}
        for ws in workspaces:
            inst = self.pool.ensure(ws)
            out[ws] = inst.base_url
        return out

    # -- run ------------------------------------------------------------------

    def _make_drive(self, client: OpenCodeClient) -> Drive:
        """Construct a Drive bound to the given worker client (overridable in tests)."""
        return Drive(
            self.settings, self.sm, client, self.reporter,
            deadline_sec=self.deadline_sec,
            meta_enabled=self.meta_enabled, meta_model=self.meta_model,
        )

    def run(self, tasks: list[ParallelTask], worker_count: int | None = None) -> dict:
        """Run all tasks in parallel (bounded by worker_count), each isolated.

        Returns {task_id: DriveResult}. A task that fails to launch or errors in
        the executor is surfaced as an ERROR DriveResult (never hangs the batch).
        """
        # ensure all instances sequentially (no port race), then run in parallel
        ws_set = list(dict.fromkeys(t.workspace for t in tasks))  # unique, ordered
        self._ensure_instances(ws_set)
        results: dict[str, DriveResult] = {}
        lock = threading.Lock()

        def _go(task: ParallelTask) -> None:
            try:
                inst = self.pool.get(task.workspace)
                if inst is None:
                    raise RuntimeError(f"no instance for workspace '{task.workspace}'")
                client = OpenCodeClient(
                    inst.base_url, model=self.settings.model,
                    timeout=self.settings.request_timeout)
                dr = self._make_drive(client).run(task.context, title=task.task_id)
            except Exception as exc:
                dr = DriveResult("error", detail=str(exc), supervisor="parallel_error")
            with lock:
                results[task.task_id] = dr

        if worker_count and worker_count > 0:
            # bounded parallelism: run at most worker_count threads at a time
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(max_workers=worker_count) as ex:
                list(ex.map(lambda t: _go(t), tasks))
        else:
            threads = [threading.Thread(target=_go, args=(t,), daemon=True)
                       for t in tasks]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        return results

    @staticmethod
    def auto_workspaces(task_ids: list[str], requested: list[str],
                        prefix: str = "parallel") -> list[str]:
        """Assign each task a workspace: use requested ones, pad with unique auto ones."""
        out: list[str] = []
        used = set()
        for i, tid in enumerate(task_ids):
            if i < len(requested) and requested[i]:
                ws = requested[i]
                base = ws
                n = 1
                while base in used:
                    base = f"{ws}-{n}"
                    n += 1
                out.append(base)
                used.add(base)
            else:
                ws = f"{prefix}-{i + 1}"
                while ws in used:
                    ws += "-x"
                out.append(ws)
                used.add(ws)
        return out
