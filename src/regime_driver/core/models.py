"""Core domain model definitions (pure pydantic, no I/O).

These are the single source of truth for the regime state machine, the
reviewer JSON contract, and the segment report. Nothing in this module may
perform network I/O, file access, or logging.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator

# --- state machine ---------------------------------------------------------

# Node type: what a node DOES (independent of which role owns it).
#   agent : let a role (a session) do work   (e.g. developer implements)
#   judge : judge a verdict via deterministic gate + intelligence (reviewer)
#   tool  : execute a deterministic tool
#   route : branch to a next node by condition
#   gate  : hard gate (must-pass)
class NodeType(str, Enum):
    AGENT = "agent"
    JUDGE = "judge"
    TOOL = "tool"
    ROUTE = "route"
    GATE = "gate"


DEFAULT_WORK_DONE_MARKER = "[WORK_DONE]"


class Outcome(str, Enum):
    """Terminal outcome of a full flow run (RunResult)."""

    COMPLETE = "complete"
    ERROR = "error"
    TIMEOUT = "timeout"
    BLOCKED = "blocked"
    HUMAN = "human"
    ABORTED = "aborted"


class SegmentOutcome(str, Enum):
    """Outcome of a single developer segment (SegmentResult)."""

    COMPLETE = "complete"
    TIMEOUT = "timeout"
    ERROR = "error"
    CANCELLED = "cancelled"


class Branch(BaseModel):
    """A conditional transition (used e.g. by the goal-lifestyle C block check)."""

    when: str
    goto: str


class Node(BaseModel):
    """A single node in a flow.

    Node is a WORK UNIT (skill + requirement), NOT a role. The `role` field
    names which user-registered role (session) owns this node. The same role
    can own many nodes; different roles occupy different sessions.
    """

    id: str
    desc: str
    role: str = "developer"          # user-registered role id (arbitrary)
    type: NodeType = NodeType.AGENT  # what the node does
    skill: str | None = None
    next: str | None = None
    branches: list[Branch] | None = None
    tool: str | None = None               # tool name for TOOL nodes (see core/tools.py)
    tool_args: dict | None = None          # args passed to that tool
    # --- node capability boundary (restores the template's division of labor) --
    # readonly: the executing agent may only READ (no write/edit/delete); file
    # mutation must wait for a writable node. Prevents "understand does all the
    # engineering" and gives the design judge something un-built to review.
    readonly: bool = Field(default=False)
    # verify: an OPTIONAL host-side shell command the driver runs when ENTERING
    # this (judge) node, whose result is fed to the judge as independent runtime
    # evidence (e.g. `docker exec {container} ... pytest`). `{container}` is
    # substituted from settings.worker_container. Only runs when
    # settings.verify_enabled is true (preflight/offline runs keep it off).
    verify: str | None = Field(default=None)


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


# --- reviewer contract (DESIGN §4) -----------------------------------------

Verdict = Literal[
    "issue_resolved", "issue_pending", "blocked", "advance", "human_escalate"
]
Action = Literal[
    "ask_developer", "request_context", "advance", "abort_session", "report_user",
    "ask_human",
]


class ReviewerVerdict(BaseModel):
    """The fixed JSON contract between the driver (fixed code) and the reviewer."""

    node: str
    verdict: Verdict
    action: Action
    message_to_developer: str | None = None
    next_state: str | None = None
    context_requested: str | None = None
    human_question: str | None = None   # ask_human: the question posed to the dialog
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    # structured findings: the reviewer's substantive review — blocking issues
    # force a non-advance action through the deterministic gate.
    issues: list["ReviewerIssue"] | None = Field(default_factory=list)

    @field_validator("issues", mode="before")
    @classmethod
    def _normalize_issues(cls, v):
        # a lax model echoing `issues: null` must not fail the whole verdict
        return v if v is not None else []


class ReviewerIssue(BaseModel):
    """A structured finding attached to a reviewer verdict.

    `severity=blocking` means the current deliverable must NOT advance: the
    deterministic gate rejects any advance that carries an unresolved blocking
    issue (a reviewer cannot mark a real problem and still wave it through).
    `severity=warning` is a documented non-blocking concern (may advance).
    """

    severity: Literal["blocking", "warning"]
    summary: str
    detail: str | None = None


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