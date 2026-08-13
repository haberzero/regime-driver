import threading
import time

import pytest

from scheduler import Scheduler


def test_empty_run_returns_empty():
    s = Scheduler()
    assert s.run() == {}


def test_serial_chain_results_and_order():
    s = Scheduler()
    s.add("a", [], lambda: 1)
    s.add("b", ["a"], lambda: 2)
    s.add("c", ["b"], lambda: 3)
    results = s.run(max_parallel=1)
    assert results == {"a": 1, "b": 2, "c": 3}
    assert s.end_times["a"] <= s.start_times["b"]
    assert s.end_times["b"] <= s.start_times["c"]


def test_dependencies_finish_before_dependents():
    s = Scheduler()
    s.add("a", [], lambda: time.sleep(0.02) or "A")
    s.add("b", [], lambda: time.sleep(0.02) or "B")
    s.add("c", ["a", "b"], lambda: "C")
    results = s.run(max_parallel=2)
    assert results == {"a": "A", "b": "B", "c": "C"}
    assert s.end_times["a"] <= s.start_times["c"]
    assert s.end_times["b"] <= s.start_times["c"]


def test_parallel_fanout_all_results():
    s = Scheduler()
    s.add("root", [], lambda: 0)
    for i in range(8):
        s.add(f"leaf{i}", ["root"], lambda i=i: i)
    results = s.run(max_parallel=4)
    assert results["root"] == 0
    assert all(results[f"leaf{i}"] == i for i in range(8))
    assert len(results) == 9


def test_forward_reference_allowed_at_add():
    s = Scheduler()
    s.add("a", ["b"], lambda: 1)
    s.add("b", [], lambda: 2)
    assert s.run() == {"a": 1, "b": 2}


def test_self_dependency_raises_at_add():
    s = Scheduler()
    with pytest.raises(ValueError) as exc:
        s.add("a", ["a"], lambda: 1)
    assert "a" in str(exc.value)


def test_cycle_detected_at_run_lists_members():
    s = Scheduler()
    s.add("a", ["b"], lambda: 1)
    s.add("b", ["c"], lambda: 2)
    s.add("c", ["a"], lambda: 3)
    with pytest.raises(ValueError) as exc:
        s.run()
    msg = str(exc.value)
    assert "a" in msg and "b" in msg and "c" in msg


def test_two_node_cycle_detected_at_run():
    s = Scheduler()
    s.add("a", ["b"], lambda: 1)
    s.add("b", ["a"], lambda: 2)
    with pytest.raises(ValueError) as exc:
        s.run()
    assert "a" in str(exc.value) and "b" in str(exc.value)


def test_missing_dependency_raises_keyerror():
    s = Scheduler()
    s.add("a", [], lambda: 1)
    s.add("b", ["ghost"], lambda: 2)
    with pytest.raises(KeyError) as exc:
        s.run()
    assert "ghost" in str(exc.value)


def test_exception_isolation_default():
    s = Scheduler()

    def boom():
        raise ValueError("bad")

    s.add("a", [], lambda: 10)
    s.add("b", ["a"], boom)
    s.add("c", ["a"], lambda: 30)
    s.add("d", ["b"], lambda: 40)
    results = s.run()
    assert results["a"] == 10
    assert isinstance(results["b"], ValueError)
    assert "bad" in str(results["b"])
    assert results["c"] == 30
    assert results["d"] == 40


def test_each_task_runs_exactly_once():
    calls = {}

    def make_fn(name):
        def f():
            calls[name] = calls.get(name, 0) + 1
            time.sleep(0.01)
            return name

        return f

    s = Scheduler()
    for i in range(6):
        deps = [] if i == 0 else [f"t{i - 1}"]
        s.add(f"t{i}", deps, make_fn(f"t{i}"))
    s.run(max_parallel=4)
    assert calls == {f"t{i}": 1 for i in range(6)}


def test_max_parallel_caps_concurrency():
    lock = threading.Lock()
    active = 0
    peak = 0

    def make_fn():
        def f():
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.05)
            with lock:
                active -= 1
            return peak

        return f

    s = Scheduler()
    for i in range(10):
        s.add(f"t{i}", [], make_fn())
    results = s.run(max_parallel=4)
    assert peak <= 4
    assert peak >= 2
    assert s.peak_active <= 4
    assert len(results) == 10


def test_max_parallel_one_is_serial():
    lock = threading.Lock()
    active = 0
    peak = 0

    def make_fn():
        def f():
            nonlocal active, peak
            with lock:
                active += 1
                peak = max(peak, active)
            time.sleep(0.01)
            with lock:
                active -= 1

        return f

    s = Scheduler()
    for i in range(5):
        s.add(f"t{i}", [], make_fn())
    s.run(max_parallel=1)
    assert peak == 1


def test_stop_on_error_raises_and_waits_for_inflight():
    started = threading.Event()

    def ok_fn():
        started.set()
        time.sleep(0.05)
        return 1

    def fail_fn():
        started.wait(timeout=5)
        raise RuntimeError("boom")

    s = Scheduler()
    s.add("ok", [], ok_fn)
    s.add("fail", [], fail_fn)
    s.add("never", ["ok"], lambda: 2)
    with pytest.raises(RuntimeError, match="boom"):
        s.run(stop_on_error=True)
    assert "never" not in s.start_times
    assert "ok" in s.end_times


def test_stop_on_error_invalid_max_parallel():
    s = Scheduler()
    s.add("a", [], lambda: 1)
    with pytest.raises(ValueError):
        s.run(max_parallel=0)
    with pytest.raises(ValueError):
        s.run(max_parallel=-1)
