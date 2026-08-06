"""Tests for stage-4 root safety invariants (runtime-enforced constitution)."""

import pytest

from regime_driver.app.runtime_invariants import (
    ROLE_GOVERNED,
    ROLE_HUMAN,
    ROLE_WATCHDOG,
    enforce,
    has_active_watchdog,
    has_inextinguishable_stop_channel,
)
from regime_driver.app.statechart_runtime import Runtime, ThreadedUnit
from regime_driver.core.statechart import SignalKind, StatechartUnit


def _governed(unit_id="work"):
    return ThreadedUnit(unit_id, role=ROLE_GOVERNED)


def _watchdog(unit_id="constitution"):
    u = ThreadedUnit(unit_id, role=ROLE_WATCHDOG)
    u.register(SignalKind.STOP, lambda s: None)
    return u


def test_has_active_watchdog():
    assert has_active_watchdog([_watchdog(), _governed()]) is True
    assert has_active_watchdog([_governed()]) is False


def test_has_inextinguishable_stop_channel():
    wd = ThreadedUnit("w", role=ROLE_WATCHDOG)
    wd.register(SignalKind.STOP, lambda s: None)
    hum = ThreadedUnit("h", role=ROLE_HUMAN)
    hum.register(SignalKind.STOP, lambda s: None)
    gov = _governed()
    assert has_inextinguishable_stop_channel([wd]) is True
    assert has_inextinguishable_stop_channel([hum]) is True
    # a governed unit that handles STOP does NOT count (AI can override it)
    assert has_inextinguishable_stop_channel([gov]) is False


def test_enforce_all_ok():
    units = [_watchdog(), _governed()]
    res = enforce(units, meta_depth=1, max_meta_depth=8)
    assert res.ok is True
    assert res.violations == []


def test_enforce_no_watchdog_violation():
    res = enforce([_governed()], meta_depth=0)
    assert res.ok is False
    assert any("I1" in v for v in res.violations)


def test_enforce_no_stop_channel_violation():
    # watchdog present but does NOT handle STOP; only governed handles stop
    wd = ThreadedUnit("w", role=ROLE_WATCHDOG)  # no STOP handler
    gov = _governed()
    gov.register(SignalKind.STOP, lambda s: None)
    res = enforce([wd, gov])
    assert any("I2" in v for v in res.violations)


def test_enforce_meta_depth_violation():
    res = enforce([_watchdog()], meta_depth=8, max_meta_depth=8)
    assert res.ok is False
    assert any("I3" in v for v in res.violations)


def test_runtime_start_refuses_without_watchdog():
    rt = Runtime()
    rt.register(_governed())  # no watchdog, no stop channel
    with pytest.raises(RuntimeError, match="root invariant"):
        rt.start()


def test_runtime_start_accepts_with_watchdog():
    rt = Runtime()
    rt.register(_watchdog())
    rt.register(_governed())
    rt.start()  # ok
    rt.stop()


def test_runtime_can_disable_enforcement():
    rt = Runtime(enforce_invariants=False)
    rt.register(_governed())
    rt.start()  # no enforcement -> allowed
    rt.stop()