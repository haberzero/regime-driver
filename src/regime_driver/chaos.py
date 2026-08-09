"""Chaos harness: fault injection + recovery verification (adverse-condition ops).

Moves the correction ladder from "can be demonstrated" to "systematically tested
under injected faults". A `FaultInjector` drives real faults against worker
instances via docker (kill/stop/start/restart), and `regime chaos` exposes the
scenarios. This complements the Supervisor's T1/L4 restart recovery with a
repeatable harness (see test_e2e_worker.test_real_supervisor_t1_restart_recovery).

Scenarios (gated real E2E):
  * worker-crash-recovery: kill a workspace's worker container, then recover it
    (docker start) and verify the opencode instance comes back healthy.

Pure-ish: the injector is thin docker ops (uses WorkerPool._run_docker), so the
docker interaction is unit-testable with a fake; the recovery is a real E2E.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .worker import WorkerPool, _run_docker


@dataclass
class FaultResult:
    """Outcome of a fault injection / recovery action."""

    fault: str
    workspace: str
    ok: bool
    detail: str = ""

    def to_dict(self) -> dict:
        return {"fault": self.fault, "workspace": self.workspace,
                "ok": self.ok, "detail": self.detail}


class FaultInjector:
    """Inject + recover faults on worker instances (docker-backed)."""

    def __init__(self, pool: WorkerPool | None = None) -> None:
        self.pool = pool or WorkerPool()

    def _container(self, workspace: str) -> str:
        return self.pool.container_for(workspace)

    def kill(self, workspace: str) -> FaultResult:
        """SIGKILL the instance's container (simulates a hard crash)."""
        try:
            _run_docker(["kill", self._container(workspace)], timeout=30)
            return FaultResult("kill", workspace, True)
        except Exception as exc:
            return FaultResult("kill", workspace, False, str(exc))

    def stop(self, workspace: str) -> FaultResult:
        """Gracefully stop the instance's container."""
        try:
            _run_docker(["stop", self._container(workspace)], timeout=60)
            return FaultResult("stop", workspace, True)
        except Exception as exc:
            return FaultResult("stop", workspace, False, str(exc))

    def start(self, workspace: str) -> FaultResult:
        """Start a stopped/killed instance's container."""
        try:
            _run_docker(["start", self._container(workspace)], timeout=60)
            return FaultResult("start", workspace, True)
        except Exception as exc:
            return FaultResult("start", workspace, False, str(exc))

    def restart(self, workspace: str) -> FaultResult:
        """Restart the instance's container (docker restart)."""
        try:
            _run_docker(["restart", self._container(workspace)], timeout=60)
            return FaultResult("restart", workspace, True)
        except Exception as exc:
            return FaultResult("restart", workspace, False, str(exc))

    def healthy(self, workspace: str, timeout: float = 5.0) -> bool:
        """True if the workspace instance's opencode is healthy."""
        inst = self.pool.get(workspace)
        if inst is None:
            return False
        from .infra.opencode import OpenCodeClient
        try:
            return OpenCodeClient(inst.base_url, timeout=timeout).health()
        except Exception:
            return False

    # -- scenarios ------------------------------------------------------------

    SCENARIOS = ("worker-crash-recovery",)

    def run_scenario(self, scenario: str, workspace: str,
                     wait_healthy_sec: float = 120.0) -> list[FaultResult]:
        """Run a named recovery scenario; returns the action log."""
        if scenario not in self.SCENARIOS:
            raise ValueError(f"unknown scenario '{scenario}' (one of {self.SCENARIOS})")
        import time
        log = []
        # ensure the container is running first (idempotent), then crash it
        log.append(self.start(workspace))
        if not self.healthy(workspace):
            # still not up; wait briefly for start to take effect
            deadline = time.time() + 30
            while time.time() < deadline:
                if self.healthy(workspace):
                    break
                time.sleep(1)
        log.append(self.kill(workspace))
        if not log[-1].ok:
            return log
        # wait for the instance to be DOWN (kill takes effect), then recover
        down = False
        deadline = time.time() + 30
        while time.time() < deadline:
            if not self.healthy(workspace):
                down = True
                break
            time.sleep(1)
        log.append(FaultResult("observe_down", workspace, down))
        log.append(self.start(workspace))
        # wait for recovery
        deadline = time.time() + wait_healthy_sec
        recovered = False
        while time.time() < deadline:
            if self.healthy(workspace):
                recovered = True
                break
            time.sleep(2)
        log.append(FaultResult("observe_recovered", workspace, recovered))
        return log
