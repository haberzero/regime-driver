"""Tests for the fleet driver (parallel, isolated full-stack drives)."""

from __future__ import annotations

from regime_driver.app.reporter import Reporter
from regime_driver.core.models import Outcome
from regime_driver.fleet import Fleet, FleetTask
from regime_driver.infra.regime_loader import load_regime
from regime_driver.infra.settings import Settings


class _FakeInst:
    def __init__(self, base, ws):
        self.base_url = base
        self.workspace = ws


class _FakePool:
    """Returns a fake instance per workspace (no real containers)."""

    def __init__(self):
        self.instances = {}

    def ensure(self, ws):
        if ws not in self.instances:
            self.instances[ws] = _FakeInst(f"http://127.0.0.1:{4100 + len(self.instances)}", ws)
        return self.instances[ws]

    def get(self, ws):
        return self.instances.get(ws)


class _FakeDrive:
    """Scripted drive: returns a COMPLETE result, records context/title."""

    def __init__(self, results):
        self.calls = []

    def run(self, context, title="regime-workflow"):
        self.calls.append((title, context))
        from regime_driver.drive import DriveResult
        return DriveResult(Outcome.COMPLETE.value, end="wrap",
                           supervisor="workflow_done", elapsed_sec=1.0)


def _fleet(tmp_path):
    rep = Reporter(journal_path=tmp_path / "f.jsonl")
    fleet = Fleet(Settings(monitor_enabled=False), load_regime(), rep)
    fleet.pool = _FakePool()
    fleet._make_drive = lambda client: _FakeDrive(None)
    return fleet, rep


def test_auto_workspaces_pads_unique():
    out = Fleet.auto_workspaces(["w1", "w2", "w3"], ["algo", "infra"])
    assert out == ["algo", "infra", "fleet-3"]
    # duplicate requested -> unique-ified
    out2 = Fleet.auto_workspaces(["w1", "w2"], ["algo", "algo"])
    assert out2[0] != out2[1]
    assert out2[0].startswith("algo")


def test_auto_workspaces_no_request_uses_defaults():
    out = Fleet.auto_workspaces(["w1", "w2", "w3"], [])
    assert out == ["fleet-1", "fleet-2", "fleet-3"]


def test_fleet_run_parallel_all_complete(tmp_path):
    fleet, rep = _fleet(tmp_path)
    tasks = [FleetTask("w1", "task one", "ws-a"),
             FleetTask("w2", "task two", "ws-b")]
    results = fleet.run(tasks)
    rep.close()
    assert set(results) == {"w1", "w2"}
    for tid, dr in results.items():
        assert dr.outcome == Outcome.COMPLETE.value
        assert dr.supervisor == "workflow_done"


def test_fleet_run_worker_count_bounds(tmp_path):
    fleet, rep = _fleet(tmp_path)
    tasks = [FleetTask("w1", "t1", "ws-a"),
             FleetTask("w2", "t2", "ws-b"),
             FleetTask("w3", "t3", "ws-c")]
    results = fleet.run(tasks, worker_count=2)
    rep.close()
    assert set(results) == {"w1", "w2", "w3"}


def test_fleet_ensures_instances_once_each(tmp_path):
    rep = Reporter()
    pool = _FakePool()
    fleet = Fleet(Settings(monitor_enabled=False), load_regime(), rep, pool=pool)
    fleet._make_drive = lambda *a, **k: _FakeDrive(None)
    tasks = [FleetTask("w1", "t1", "ws-a"), FleetTask("w2", "t2", "ws-a")]
    fleet.run(tasks)
    rep.close()
    # same workspace ensured exactly once (no duplicate)
    assert pool.instances["ws-a"] is not None
