"""Tests for the chaos harness (fault injection + recovery)."""

from __future__ import annotations

from regime_driver.chaos import FaultInjector, FaultResult


class _FakeDocker:
    """Records docker calls; simulates kill stopping the 'container'."""

    def __init__(self):
        self.calls = []
        self.killed = False

    def __call__(self, args, timeout=120.0):
        self.calls.append(list(args))
        from subprocess import CompletedProcess
        if args[0] == "kill":
            self.killed = True
        elif args[0] in ("start", "restart"):
            self.killed = False
        return CompletedProcess(args, 0, b"", b"")


class _FakePool:
    def __init__(self):
        self._healthy = True
        self.container = "opencode-worker-algo"

    def container_for(self, ws):
        return self.container

    def get(self, ws):
        from regime_driver.worker import WorkerInstance
        return WorkerInstance("algo", self.container, 4200,
                              "http://127.0.0.1:4200", self.container, "/ws", self._healthy)


class _FakeInjector(FaultInjector):
    """Injector whose health reflects the fake's killed state."""

    def __init__(self):
        self.pool = _FakePool()
        self.docker = _FakeDocker()
        self.pool._healthy = True

    def _docker(self, args, timeout=120.0):
        return self.docker(args, timeout)

    def healthy(self, workspace, timeout=5.0):
        return not self.docker.killed


def test_scenarios_known():
    assert "worker-crash-recovery" in FaultInjector.SCENARIOS


def test_unknown_scenario_raises():
    inj = _FakeInjector()
    try:
        inj.run_scenario("nope", "algo")
        assert False, "should raise"
    except ValueError:
        pass


def test_run_scenario_recovers():
    inj = _FakeInjector()
    # make the injector use fake docker directly
    import regime_driver.chaos as chaos_mod
    chaos_mod._run_docker = inj.docker
    log = inj.run_scenario("worker-crash-recovery", "algo", wait_healthy_sec=5)
    actions = [l.fault for l in log]
    assert "kill" in actions and "start" in actions
    assert all(l.ok for l in log)
    # worker recovered
    assert log[-1].fault == "observe_recovered" and log[-1].ok


def test_fault_injector_single_actions():
    inj = FaultInjector(pool=_FakePool())
    # use fake docker for the container ops
    import regime_driver.chaos as chaos_mod
    fake = _FakeDocker()
    chaos_mod._run_docker = fake
    assert inj.kill("algo").ok
    assert inj.start("algo").ok
    assert inj.restart("algo").ok
    # health uses a real OpenCodeClient -> injector.healthy False on bad port
    assert inj.healthy("algo") is False
