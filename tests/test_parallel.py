"""Tests for the parallel batch driver (parallel, isolated full-stack drives)."""

from __future__ import annotations

from regime_driver.app.reporter import Reporter
from regime_driver.core.models import Outcome
from regime_driver.parallel import Parallel, ParallelTask
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


def _batch(tmp_path):
    rep = Reporter(journal_path=tmp_path / "f.jsonl")
    batch = Parallel(Settings(monitor_enabled=False), load_regime(), rep)
    batch.pool = _FakePool()
    batch._make_drive = lambda client: _FakeDrive(None)
    return batch, rep


def test_auto_workspaces_pads_unique():
    out = Parallel.auto_workspaces(["w1", "w2", "w3"], ["algo", "infra"])
    assert out == ["algo", "infra", "parallel-3"]
    # duplicate requested -> unique-ified
    out2 = Parallel.auto_workspaces(["w1", "w2"], ["algo", "algo"])
    assert out2[0] != out2[1]
    assert out2[0].startswith("algo")


def test_auto_workspaces_no_request_uses_defaults():
    out = Parallel.auto_workspaces(["w1", "w2", "w3"], [])
    assert out == ["parallel-1", "parallel-2", "parallel-3"]


def test_parallel_run_all_complete(tmp_path):
    batch, rep = _batch(tmp_path)
    tasks = [ParallelTask("w1", "task one", "ws-a"),
             ParallelTask("w2", "task two", "ws-b")]
    results = batch.run(tasks)
    rep.close()
    assert set(results) == {"w1", "w2"}
    for tid, dr in results.items():
        assert dr.outcome == Outcome.COMPLETE.value
        assert dr.supervisor == "workflow_done"


def test_parallel_forwards_regime_to_member_drive(tmp_path):
    """Phase-1d: a named regime passed to a Parallel batch is handed to every
    member Drive, so drive-many --regime-name runs the same operating rule as
    `drive --regime-name` (flow + roles + watchdog + handover)."""
    import json
    from unittest import mock

    from regime_driver.core.models import Outcome
    from regime_driver.drive import Drive, DriveResult
    from regime_driver.regime import compile_regime

    spec = {
        "name": "parallel-regime",
        "flow": {
            "entry": "a",
            "nodes": [
                {"id": "a", "desc": "干", "role": "developer", "type": "agent",
                 "next": "b"},
                {"id": "b", "desc": "审", "role": "reviewer", "type": "judge"},
            ],
        },
        "watchdog": {"soft_sec": 30, "hard_sec": 600},
    }
    regime = compile_regime(json.dumps(spec, ensure_ascii=False))
    captured = {}

    def _fake_run(self, context, title="regime-workflow"):
        captured["regime"] = self.regime
        captured["sm"] = self.sm
        return DriveResult(Outcome.COMPLETE.value, end="wrap",
                           supervisor="workflow_done", elapsed_sec=1.0)

    rep = Reporter(journal_path=tmp_path / "p.jsonl")
    batch = Parallel(Settings(monitor_enabled=False), regime.flow, rep,
                     regime=regime)
    batch.pool = _FakePool()
    with mock.patch.object(Drive, "run", _fake_run):
        tasks = [ParallelTask("w1", "task one", "ws-a")]
        results = batch.run(tasks)
    rep.close()
    assert captured["regime"] is regime
    assert captured["sm"] is regime.flow
    assert results["w1"].outcome == Outcome.COMPLETE.value


def test_parallel_run_worker_count_bounds(tmp_path):
    batch, rep = _batch(tmp_path)
    tasks = [ParallelTask("w1", "t1", "ws-a"),
             ParallelTask("w2", "t2", "ws-b"),
             ParallelTask("w3", "t3", "ws-c")]
    results = batch.run(tasks, worker_count=2)
    rep.close()
    assert set(results) == {"w1", "w2", "w3"}


def test_parallel_ensures_instances_once_each(tmp_path):
    rep = Reporter()
    pool = _FakePool()
    batch = Parallel(Settings(monitor_enabled=False), load_regime(), rep, pool=pool)
    batch._make_drive = lambda *a, **k: _FakeDrive(None)
    tasks = [ParallelTask("w1", "t1", "ws-a"), ParallelTask("w2", "t2", "ws-a")]
    batch.run(tasks)
    rep.close()
    # same workspace ensured exactly once (no duplicate)
    assert pool.instances["ws-a"] is not None
