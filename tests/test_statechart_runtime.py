"""Tests for stage-2 parallel statechart runtime (threads + async delivery)."""

import threading

from regime_driver.app.statechart_runtime import Runtime, ThreadedUnit
from regime_driver.core.statechart import SignalKind


def test_unit_processes_delivered_signal_on_own_thread():
    """A delivered signal is handled on the unit's own thread, not the caller's."""
    unit = ThreadedUnit("work")
    unit.start()
    unit_tid = unit._thread.ident  # the unit's dedicated thread id
    main_tid = threading.get_ident()
    seen = []

    def handler(sig):
        seen.append(threading.get_ident())

    unit.register(SignalKind.NOTIFY, handler)
    unit.deliver(_sig(SignalKind.NOTIFY, "who"))
    # wait for the unit thread to process
    deadline = _deadline()
    while not seen and _now() < deadline:
        pass
    unit.stop()
    assert seen and seen[0] != main_tid
    assert seen[0] == unit_tid  # handled on the unit's own thread, not the caller's


def test_runtime_ping_pong_between_units():
    """Two units running on separate threads drive each other via signals."""
    rt = Runtime()
    done = threading.Event()

    # A: on RETRY, record who stopped it and signal completion
    a = ThreadedUnit("A")
    result = []

    def a_on_retry(sig):
        result.append(sig.get("who"))
        done.set()

    a.register(SignalKind.RETRY, a_on_retry)

    # B: on STOP, post a RETRY back to A (its own thread replies)
    b = ThreadedUnit("B")

    def b_on_stop(sig):
        rt.post("B", "A", SignalKind.RETRY, {"who": "B"})

    b.register(SignalKind.STOP, b_on_stop)

    rt.register(a).register(b).start()
    rt.post("constitution", "B", SignalKind.STOP)
    assert done.wait(timeout=5.0), "A never received the RETRY from B"
    rt.stop()
    assert result == ["B"]


def test_broadcast_delivers_to_all_units():
    rt = Runtime()
    got = []
    for name in ("u1", "u2"):
        u = ThreadedUnit(name)
        u.register(SignalKind.NUDGE, lambda s, n=name: got.append(n))
        rt.register(u)
    rt.start()
    rt.broadcast("constitution", SignalKind.NUDGE)
    deadline = _deadline()
    while len(got) < 2 and _now() < deadline:
        pass
    rt.stop()
    assert sorted(got) == ["u1", "u2"]


def test_handler_error_does_not_kill_runtime():
    rt = Runtime()
    seen = []
    unit = ThreadedUnit("work")

    def handler(sig):
        if sig.get("boom"):
            raise RuntimeError("boom")
        seen.append(sig.get("n"))

    unit.register(SignalKind.NOTIFY, handler)
    rt.register(unit).start()
    rt.post("x", "work", SignalKind.NOTIFY, {"boom": True})
    rt.post("x", "work", SignalKind.NOTIFY, {"n": 1})
    deadline = _deadline()
    while not seen and _now() < deadline:
        pass
    rt.stop()
    assert seen == [1]  # the erroring signal was swallowed, next one processed
    assert unit._thread is None  # stopped cleanly


def test_stop_joins_unit_thread():
    unit = ThreadedUnit("work")
    unit.start()
    assert unit._thread is not None and unit._thread.is_alive()
    unit.stop()
    assert unit._thread is None


def test_post_unknown_target_returns_false():
    rt = Runtime()
    rt.register(ThreadedUnit("a"))
    assert rt.post("a", "nobody", SignalKind.STOP) is False


# -- helpers ----------------------------------------------------------------

def _sig(kind, src, **payload):
    from regime_driver.core.statechart import Signal
    return Signal(kind, src, "work", payload or None)


def _deadline(sec=3.0):
    import time
    return time.time() + sec


def _now():
    import time
    return time.time()