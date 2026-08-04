"""State machine loading, validation, and traversal (pure domain logic).

Turns a parsed regime descriptor into a Regime model and provides ordered
traversal of a flow. This module is PURE: it performs no file or network I/O.
File loading lives in infra (see infra/regime_loader.py).
"""

from __future__ import annotations

import json

from .models import Flow, Node, Regime


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

    def actor(self, node_id: str) -> str:
        return self.node(node_id).actor

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