"""Stage-4b: user can inject their OWN constitution/watchdog unit (overridable).

The whole point of making the constitution a peer state machine is that a user
can supply their own watchdog logic instead of the built-in ConstitutionUnit.
This file demonstrates the override mechanism: a user-defined watchdog with
custom detection, registered into a Runtime, satisfies the root invariants and
performs its own detection + STOP control.
"""

import time

from regime_driver.app.runtime_invariants import ROLE_WATCHDOG
from regime_driver.app.statechart_runtime import Runtime, ThreadedUnit
from regime_driver.core.statechart import SignalKind


class UserWatchdog(ThreadedUnit):
    """A user-defined constitution: stops a unit if any report's output grows
    beyond a threshold (totally custom policy, not the built-in one)."""

    def __init__(self, unit_id="my-constitution", max_output=1000, bus=None):
        super().__init__(unit_id, bus, role=ROLE_WATCHDOG)
        self.max_output = max_output
        self.register(SignalKind.REPORT, self._on_report)
        self.register(SignalKind.STOP, lambda s: None)  # satisfy I2 (non-governed)

    def _on_report(self, signal):
        out = int((signal.payload or {}).get("output") or 0)
        if out > self.max_output:
            self.bus.broadcast(self.id, SignalKind.STOP,
                               {"reason": f"output {out} > {self.max_output}", "kind": "custom"})
            self.emit("custom_watchdog_fire", output=out)


def _wait_until(cond, timeout=3.0):
    deadline = time.time() + timeout
    while not cond() and time.time() < deadline:
        pass
    return cond()


def test_user_watchdog_satisfies_invariants_and_fires():
    rt = Runtime()  # enforcement ON
    got = []

    work = ThreadedUnit("work")
    work.register(SignalKind.STOP, lambda s: got.append(s.get("kind")))
    work.register(SignalKind.REPORT, lambda s: None)

    my_watchdog = UserWatchdog(max_output=100, bus=rt.bus)
    rt.register(work).register(my_watchdog)
    rt.start()  # must not raise: watchdog + non-governed STOP channel

    rt.post("work", my_watchdog.id, SignalKind.REPORT, {"output": 99})
    _wait_until(lambda: False, timeout=0.2)  # brief settle
    assert got == []  # under threshold -> no stop

    rt.post("work", my_watchdog.id, SignalKind.REPORT, {"output": 5000})
    assert _wait_until(lambda: got), "custom watchdog never fired"
    rt.stop()
    assert got == ["custom"]  # custom detection fired a STOP


def test_user_watchdog_registered_via_runtime():
    """Registering a user watchdog through the Runtime is the public override path."""
    rt = Runtime()
    work = ThreadedUnit("work")
    work.register(SignalKind.STOP, lambda s: None)
    my = UserWatchdog(unit_id="custom", max_output=999)
    rt.register(work).register(my)
    rt.start()  # invariants satisfied (watchdog + stop channel)
    assert rt.units["custom"] is my
    rt.stop()