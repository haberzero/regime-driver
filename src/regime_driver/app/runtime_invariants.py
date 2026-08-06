"""Root safety invariants, enforced by the runtime (app layer, stage 4).

The "constitution layer" is now a *peer* state machine, so its *specific*
detection policy is user-overridable. But three root invariants must survive any
overriding — otherwise an AI could "turn off its own jail". These invariants are
therefore enforced by the **runtime**, not by any single (overridable) state
machine:

I1. **At least one active watchdog** — the system may never be configured with
     zero watchdog units (a watchdog is a unit whose role is `watchdog`).
I2. **An inextinguishable stop/Esc channel** — at least one unit that is *not*
     user/governed (`watchdog` or `human`) must handle STOP, so a human/Esc
     path always exists and cannot be fully removed by an overridden model.
I3. **Meta-iteration bound** — self-modification / self-inspection recursion is
     capped (meta_depth < max_meta_depth), so an AI cannot recurse infinitely
     through "customizing its own constitution".

This module is pure logic (no I/O); the Runtime calls `enforce` at deployment.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.statechart import SignalKind, StatechartUnit

ROLE_GOVERNED = "governed"
ROLE_WATCHDOG = "watchdog"
ROLE_HUMAN = "human"


@dataclass
class InvariantResult:
    """Result of a root-invariant check."""

    ok: bool
    violations: list[str] = field(default_factory=list)

    def __bool__(self) -> bool:
        return self.ok


def has_active_watchdog(units: list[StatechartUnit]) -> bool:
    """I1: at least one watchdog unit is present/enabled."""
    return any(u.role == ROLE_WATCHDOG for u in units)


def has_inextinguishable_stop_channel(units: list[StatechartUnit]) -> bool:
    """I2: at least one non-governed unit handles STOP (human/Esc path)."""
    return any(
        u.role in (ROLE_WATCHDOG, ROLE_HUMAN) and u.handles(SignalKind.STOP)
        for u in units
    )


def check_meta_depth(current: int, max_meta_depth: int) -> bool:
    """I3: current meta recursion depth stays strictly under the cap."""
    return current < max_meta_depth


def enforce(
    units: list[StatechartUnit],
    meta_depth: int = 0,
    max_meta_depth: int = 8,
) -> InvariantResult:
    """Check all three root invariants; report every violation."""
    violations: list[str] = []
    if not has_active_watchdog(units):
        violations.append("I1: no active watchdog unit (role='watchdog')")
    if not has_inextinguishable_stop_channel(units):
        violations.append("I2: no inextinguishable STOP channel (non-governed unit handles STOP)")
    if not check_meta_depth(meta_depth, max_meta_depth):
        violations.append(f"I3: meta recursion depth {meta_depth} >= cap {max_meta_depth}")
    return InvariantResult(ok=not violations, violations=violations)