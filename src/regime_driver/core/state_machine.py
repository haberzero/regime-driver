"""State machine loading, validation, and traversal (pure domain logic).

Turns a parsed regime descriptor into a Regime model and provides ordered
traversal of a flow. This module is PURE: it performs no file or network I/O.
File loading lives in infra (see infra/regime_loader.py).
"""

from __future__ import annotations

import json

from .models import Flow, Node, NodeType, Regime
from .verify_spec import verify_command_error


class StateMachineError(Exception):
    """Raised when a regime descriptor is malformed or references are broken."""


class StateMachine:
    """A loaded, validated regime descriptor focused on one flow."""

    def __init__(self, regime: Regime, flow_name: str | None = None) -> None:
        self.regime = regime
        self.flow_name = flow_name or regime.entry.flow
        self.flow: Flow = regime.flow(self.flow_name)
        self.start: str = regime.entry.start_node
        self._validate()

    # -- construction -------------------------------------------------------

    @classmethod
    def from_dict(cls, raw: str) -> "StateMachine":
        """Parse a JSON string into a StateMachine (pure, no I/O)."""
        return cls(Regime.model_validate(json.loads(raw)))

    def _validate(self) -> None:
        """Check every node's next/branch target exists in the same flow."""
        if self.start not in self.flow.nodes:
            raise StateMachineError(f"entry start '{self.start}' not in flow '{self.flow_name}'")
        for node_id, node in self.flow.nodes.items():
            if node.next and node.next not in self.flow.nodes:
                raise StateMachineError(
                    f"node '{node_id}' next '{node.next}' not in flow '{self.flow_name}'"
                )
            for branch in node.branches or []:
                if branch.goto not in self.flow.nodes:
                    raise StateMachineError(
                        f"node '{node_id}' branch '{branch.goto}' not in flow '{self.flow_name}'"
                    )
            # W5 verify-shape guard at the SINGLE construction point: any flow
            # loaded from a store / file / registry / design must carry a verify
            # command inside the docker-exec whitelist, or it is rejected HERE —
            # never discovered mid-run when a judge node tries to run it (the
            # 2026-08-14 nightly: a store-residual `sg docker -c` wrapper around
            # docker-exec passed construction, then stalled a long task in its
            # test gate before failing loudly).
            if node.verify:
                err = verify_command_error(node.verify)
                if err is not None:
                    raise StateMachineError(
                        f"node '{node_id}' verify command is outside the whitelist: {err}"
                    )
            # semantic checks for deterministic node types (fail fast on config errors)
            if node.type == NodeType.TOOL and not node.tool:
                raise StateMachineError(f"tool node '{node_id}' must declare a tool name")
            if node.type in (NodeType.ROUTE, NodeType.GATE) and not node.branches:
                raise StateMachineError(
                    f"{node.type.value} node '{node_id}' must declare at least one branch"
                )

    # -- traversal ----------------------------------------------------------

    def node(self, node_id: str) -> Node:
        try:
            return self.flow.nodes[node_id]
        except KeyError:
            raise StateMachineError(f"no node '{node_id}' in flow '{self.flow_name}'") from None

    def next(self, node_id: str) -> str | None:
        return self.node(node_id).next

    def is_terminal(self, node_id: str) -> bool:
        return self.node(node_id).next is None

    def role(self, node_id: str) -> str:
        return self.node(node_id).role

    def node_type(self, node_id: str) -> str:
        return self.node(node_id).type.value

    def node_ids(self) -> list[str]:
        """All node ids in the current flow (for reviewer prompt / gate hints)."""
        return list(self.flow.nodes)

    def node_descriptions(self) -> dict[str, str]:
        """Map node id -> description (for the reviewer's valid-target list)."""
        return {nid: self.node(nid).desc for nid in self.flow.nodes}

    def successors(self, node_id: str) -> list[str]:
        """The valid advance targets from a node: its `next` plus branch `goto`s.

        This is the authoritative set the reviewer may advance to. Restricting
        advance to successors prevents backward/self transitions (cycle risk).
        """
        node = self.node(node_id)
        targets: list[str] = []
        if node.next:
            targets.append(node.next)
        for branch in node.branches or []:
            if branch.goto not in targets:
                targets.append(branch.goto)
        return targets

    def flow_path(self) -> list[str]:
        """Linear ordered node ids from start to terminal (raises on cycles)."""
        path: list[str] = []
        seen: set[str] = set()
        cur: str | None = self.start
        while cur is not None:
            if cur in seen:
                raise StateMachineError(f"cycle detected in flow '{self.flow_name}' at '{cur}'")
            seen.add(cur)
            path.append(cur)
            cur = self.next(cur)
        return path