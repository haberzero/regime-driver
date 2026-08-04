"""Core domain model definitions (pure pydantic, no I/O).

These are the single source of truth for the regime state machine, the
reviewer JSON contract, and the segment report. Nothing in this module may
perform network I/O, file access, or logging.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# --- state machine ---------------------------------------------------------

Actor = Literal["developer", "reviewer", "machine"]

DEFAULT_WORK_DONE_MARKER = "[WORK_DONE]"


class Branch(BaseModel):
    """A conditional transition (used e.g. by the goal-lifestyle C block check)."""

    when: str
    goto: str


class Node(BaseModel):
    """A single node in a flow."""

    id: str
    desc: str
    actor: Actor
    skill: str | None = None
    next: str | None = None
    branches: list[Branch] | None = None


class Flow(BaseModel):
    """A named flow: an ordered graph of nodes keyed by node id."""

    nodes: dict[str, Node]


class RegimeMeta(BaseModel):
    """Runtime knobs that are part of the regime descriptor."""

    source: list[str] = Field(default_factory=list)
    session_turn_check: int = 5
    work_done_marker: str = DEFAULT_WORK_DONE_MARKER


class FlowEntry(BaseModel):
    """The default flow and starting node."""

    flow: str
    start_node: str


class Regime(BaseModel):
    """Top-level model of regime.json."""

    version: str
    description: str | None = None
    meta: RegimeMeta = Field(default_factory=RegimeMeta)
    flows: dict[str, Flow]
    entry: FlowEntry

    def flow(self, name: str) -> Flow:
        try:
            return self.flows[name]
        except KeyError:
            raise KeyError(f"no flow '{name}' in regime") from None

    def node(self, flow_name: str, node_id: str) -> Node:
        return self.flow(flow_name).nodes[node_id]


# --- reviewer contract (DESIGN §4) -----------------------------------------

Verdict = Literal[
    "issue_resolved", "issue_pending", "blocked", "advance", "human_escalate"
]
Action = Literal[
    "ask_developer", "request_context", "advance", "abort_session", "report_user"
]


class ReviewerVerdict(BaseModel):
    """The fixed JSON contract between L1 (fixed code) and L0 (reviewer)."""

    node: str
    verdict: Verdict
    action: Action
    message_to_developer: str | None = None
    next_state: str | None = None
    context_requested: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str


# --- segment report ([WORK_DONE]) ------------------------------------------

class SegmentReport(BaseModel):
    """Structured report a developer returns at the end of a segment."""

    files_changed: list[str] = Field(default_factory=list)
    test_command: str | None = None
    test_result: str | None = None
    tech_debt: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)


# --- gate result -----------------------------------------------------------

class GateResult(BaseModel):
    """Outcome of the deterministic gate (contract.py)."""

    ok: bool
    reason: str
    verdict: ReviewerVerdict | None = None