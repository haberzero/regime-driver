"""Deep static validation of a flow descriptor (beyond StateMachine._validate).

`StateMachine._validate` only checks structural references (entry start, next,
branch targets, tool/route/gate shape). This module adds the *semantic* checks
that catch "valid on paper, dies when run" errors, so a flow written by
opencode can be vetted before it touches a real worker/session:

* every node's `role` is registered (else the driver cannot build its session);
* every node's `skill` actually resolves to a loadable SKILL.md;
* every TOOL node names a registered tool;
* every node is reachable from the entry start (no orphan islands);
* no cycles on the linear `next` spine (existing `flow_path` guard).

Pure domain logic: no I/O except optional skill loading via a callback.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .models import NodeType
from .role import RoleRegistry, default_roles
from .state_machine import StateMachine, StateMachineError
from .tools import TOOLS


@dataclass
class DeepCheckResult:
    """Result of deep validation: lists of issues, never raises for found issues."""

    ok: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "errors": self.errors,
            "warnings": self.warnings,
        }


def _check_roles(sm: StateMachine, roles: RoleRegistry, out: DeepCheckResult) -> None:
    for node_id, node in sm.flow.nodes.items():
        if not roles.has(node.role):
            out.errors.append(
                f"node '{node_id}' role '{node.role}' not registered "
                f"(registered: {sorted(roles.ids())})"
            )


def _check_skills(
    sm: StateMachine,
    load: Callable[[str], str],
    out: DeepCheckResult,
) -> None:
    for node_id, node in sm.flow.nodes.items():
        if not node.skill:
            continue
        try:
            load(node.skill)
        except Exception as exc:
            out.errors.append(f"node '{node_id}' skill '{node.skill}' unloadable: {exc}")


def _check_tools(sm: StateMachine, out: DeepCheckResult) -> None:
    for node_id, node in sm.flow.nodes.items():
        if node.type != NodeType.TOOL:
            continue
        if node.tool not in TOOLS:
            out.errors.append(
                f"tool node '{node_id}' unknown tool '{node.tool}' "
                f"(registered: {sorted(TOOLS)})"
            )


def _check_capability_boundaries(sm: StateMachine, out: DeepCheckResult) -> None:
    """WORK_PLAN13 dead-config guards: `verify`/`readonly` on the wrong node
    type are silently ignored — fail loudly instead."""
    for node_id, node in sm.flow.nodes.items():
        if node.verify and node.type != NodeType.JUDGE:
            out.errors.append(
                f"node '{node_id}' declares `verify` but is not a judge node "
                f"(verify runs only when entering a judge node; on '{node.type}' "
                f"it would be dead config)"
            )
        if node.readonly and node.type == NodeType.JUDGE:
            out.errors.append(
                f"node '{node_id}' declares `readonly` on a judge node "
                f"(judge sessions are already read-only; readonly is an agent-node "
                f"capability boundary)"
            )


def _check_reachability(sm: StateMachine, out: DeepCheckResult) -> None:
    """Every node must be reachable from the entry start over successors."""
    reachable: set[str] = set()
    stack = [sm.start]
    while stack:
        cur = stack.pop()
        if cur in reachable:
            continue
        reachable.add(cur)
        for target in sm.successors(cur):
            if target not in reachable:
                stack.append(target)
    for node_id in sm.flow.nodes:
        if node_id not in reachable:
            out.warnings.append(
                f"node '{node_id}' unreachable from entry '{sm.start}' (dead island)"
            )


def _check_spine_cycles(sm: StateMachine, out: DeepCheckResult) -> None:
    """Catch cycles on the linear `next` spine (flow_path already guards)."""
    try:
        sm.flow_path()
    except StateMachineError as exc:
        out.errors.append(str(exc))


def _check_branch_cycles(sm: StateMachine, out: DeepCheckResult) -> None:
    """Warn on branch `goto` back-edges (potential revisit loops).

    A back-edge via a conditional branch is a *legitimate* rework loop in these
    flows (e.g. test-fail -> design), so it is a warning, not an error. The
    runtime `max_total_nodes` cap is the anti-runaway backstop.
    """
    for node_id in sm.flow.nodes:
        reachable: set[str] = set()
        stack = list(sm.successors(node_id))
        while stack:
            cur = stack.pop()
            if cur in reachable or cur == node_id:
                continue
            reachable.add(cur)
            for t in sm.successors(cur):
                if t == node_id:
                    out.warnings.append(
                        f"node '{node_id}' reachable from itself via branches "
                        f"(rework loop); runtime max_total_nodes caps it")
                elif t not in reachable:
                    stack.append(t)


def deep_validate(
    sm: StateMachine,
    *,
    roles: RoleRegistry | None = None,
    load_skill: Callable[[str], str] | None = None,
) -> DeepCheckResult:
    """Run all deep static checks and return a collected result."""
    out = DeepCheckResult(ok=True)
    roles = roles or default_roles()
    _check_roles(sm, roles, out)
    if load_skill is not None:
        _check_skills(sm, load_skill, out)
    _check_tools(sm, out)
    _check_capability_boundaries(sm, out)
    _check_reachability(sm, out)
    _check_spine_cycles(sm, out)
    _check_branch_cycles(sm, out)
    out.ok = not out.errors
    return out
