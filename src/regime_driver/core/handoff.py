"""Handoff model — the explicit collaboration channel between roles (pure domain).

Core v2 idea: reviewer and developer are INDEPENDENT individuals, each
with a private session memory. They do NOT share context; they collaborate via
structured handoffs. This module defines the handoff documents that carry work
between roles, and the lightweight convergence detector for multi-round
interrogation.

This is pure domain logic: no I/O, no network. Handoffs are serializable so they
can be persisted to the ledger for auditability and recovery.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field

# Any role id (user-registered). The kernel does not care whether a role is
# "developer"/"reviewer"/custom — those are user-specialized instances.
Role = str

# Handoff kinds: cross-role collaboration (inquiry/report/context),
# brain-capacity rotation (brain_normal/brain_urgent), and role transition
# (role A -> role B).
HandoffKind = Literal[
    "inquiry", "report", "context",
    "brain_normal", "brain_urgent", "role_transition",
]


class Inquiry(BaseModel):
    """Reviewer->developer: a structured query demanding rework."""

    criticisms: list[str] = Field(default_factory=list)
    required_rework: str = ""
    acceptance: str = ""


class Report(BaseModel):
    """Developer->reviewer: a structured report (reviewer reads only this)."""

    files_changed: list[str] = Field(default_factory=list)
    changes: str = ""
    test_result: str = ""
    open_questions: list[str] = Field(default_factory=list)


class Handover(BaseModel):
    """Session-rotation context: what to carry into a fresh session."""

    summary: str = ""
    constraints: list[str] = Field(default_factory=list)
    pending: list[str] = Field(default_factory=list)


class Handoff(BaseModel):
    """A single handoff document exchanged between two roles.

    This is the ONLY explicit channel of collaboration. It is structured,
    serializable, and auditable. The receiver reads the `content` specific to
    the `kind`; it never reads the sender's session memory.
    """

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    kind: HandoffKind
    from_role: Role
    to_role: Role
    flow_node: str = ""
    summary: str = ""
    inquiry: Inquiry | None = None
    report: Report | None = None
    handover: Handover | None = None
    ts: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    # -- factory methods -----------------------------------------------------

    @classmethod
    def make_inquiry(cls, criticisms: list[str], required_rework: str,
                     acceptance: str = "", flow_node: str = "",
                     from_role: Role = "reviewer", to_role: Role = "developer") -> "Handoff":
        """Cross-role inquiry (from a judging role to a working role)."""
        return cls(
            kind="inquiry",
            from_role=from_role,
            to_role=to_role,
            flow_node=flow_node,
            summary=required_rework,
            inquiry=Inquiry(criticisms=criticisms, required_rework=required_rework,
                            acceptance=acceptance),
        )

    @classmethod
    def make_report(cls, files_changed: list[str], changes: str,
                    test_result: str = "", open_questions: list[str] | None = None,
                    flow_node: str = "",
                    from_role: Role = "developer", to_role: Role = "reviewer") -> "Handoff":
        """Cross-role report (from a working role back to a judging role)."""
        return cls(
            kind="report",
            from_role=from_role,
            to_role=to_role,
            flow_node=flow_node,
            summary=changes,
            report=Report(files_changed=files_changed, changes=changes,
                          test_result=test_result, open_questions=open_questions or []),
        )

    # -- aliases preserved for backward clarity ------------------------------
    @classmethod
    def reviewer_inquiry(cls, criticisms, required_rework, acceptance="", flow_node="") -> "Handoff":
        return cls.make_inquiry(criticisms, required_rework, acceptance, flow_node)

    @classmethod
    def developer_report(cls, files_changed, changes, test_result="",
                         open_questions=None, flow_node="") -> "Handoff":
        return cls.make_report(files_changed, changes, test_result, open_questions, flow_node)

    @classmethod
    def context_request(cls, requested: str, flow_node: str = "") -> "Handoff":
        return cls(kind="context", from_role="reviewer", to_role="machine",
                   flow_node=flow_node, summary=requested)

    @classmethod
    def brain_handoff(cls, kind: Literal["brain_normal", "brain_urgent"],
                      summary: str, constraints: list[str] | None = None,
                      pending: list[str] | None = None,
                      role: Role = "developer") -> "Handoff":
        """Brain-capacity handoff (same role, session rotation)."""
        return cls(kind=kind, from_role=role, to_role=role,
                   summary=summary,
                   handover=Handover(summary=summary, constraints=constraints or [],
                                     pending=pending or []))

    @classmethod
    def role_transition(cls, summary: str, from_role: Role = "reviewer",
                        to_role: Role = "reviewer",
                        constraints: list[str] | None = None,
                        pending: list[str] | None = None) -> "Handoff":
        """Role-transition handoff (reviewer A -> reviewer B, same developer)."""
        return cls(kind="role_transition", from_role=from_role, to_role=to_role,
                   summary=summary,
                   handover=Handover(summary=summary, constraints=constraints or [],
                                     pending=pending or []))

    # -- serialization -------------------------------------------------------

    def to_json(self) -> str:
        return self.model_dump_json()

    @classmethod
    def from_json(cls, raw: str) -> "Handoff":
        return cls.model_validate_json(raw)

    # -- accessors -----------------------------------------------------------

    def inquiry_text(self) -> str:
        """The developer-facing text of an inquiry handoff ('' if not inquiry)."""
        if self.kind != "inquiry" or self.inquiry is None:
            return ""
        parts = [self.inquiry.required_rework]
        if self.inquiry.acceptance:
            parts.append(f"验收：{self.inquiry.acceptance}")
        return "\n".join(p for p in parts if p)

    def report_text(self) -> str:
        """The reviewer-facing text of a report handoff ('' if not report)."""
        if self.kind != "report" or self.report is None:
            return ""
        parts = [f"改动文件: {', '.join(self.report.files_changed) or '无'}",
                 f"改动: {self.report.changes}"]
        if self.report.test_result:
            parts.append(f"测试: {self.report.test_result}")
        if self.report.open_questions:
            parts.append(f"待决: {', '.join(self.report.open_questions)}")
        return "\n".join(parts)


# ---------------------------------------------------------------------------
# Convergence detection (pure function)
# ---------------------------------------------------------------------------

def detect_loop(rounds: list[tuple[str, str]], max_identical: int = 2) -> bool:
    """Detect whether an interrogation is spinning (no progress).

    Args:
        rounds: list of (inquiry_text, report_text) per round.
        max_identical: if the same inquiry text repeats this many times with no
            change in the report, declare a loop.

    Returns:
        True if the interrogation is looping, else False.
    """
    if len(rounds) < 2:
        return False
    # count consecutive identical inquiries
    last_inquiry = rounds[-1][0]
    identical_count = 1
    for inquiry, _ in reversed(rounds[:-1]):
        if inquiry == last_inquiry:
            identical_count += 1
        else:
            break
    if identical_count >= max_identical:
        # if reports are also unchanged, it's a true spin
        last_report = rounds[-1][1]
        if all(rpt == last_report for _, rpt in rounds[-identical_count:]):
            return True
    return False