"""Role policy — programmable strategy for session lifecycle (pure domain).

Core v3 idea: a session is a "tiring person"; it must self-assess and decide to
hand off. The policy controls WHEN and HOW — thresholds, self-assessment,
handoff messages — and is user-programmable (Python + templates). Developer and
reviewer are the same abstraction; only the written policy differs.

This module is pure: no I/O. It defines the strategy contract and default
policies. The self-assessment protocol (verdict + remaining_rounds) is defined
here too.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Literal

Normalized = Literal["CONTINUE", "ROTATE", "HANDOFF_NOW"]


class TransitionDecision(str, Enum):
    """How a role handles its session when the flow advances to another node.

    Reuse  : keep the current session (context persists).
    Rotate : hand off to a fresh session (write handover, open new).
    Anchor : stay as a stable anchor (others may rotate, this one does not).
    """

    REUSE = "reuse"
    ROTATE = "rotate"
    ANCHOR = "anchor"


@dataclass
class SelfAssessment:
    """The deterministic, parseable protocol a session returns on self-eval."""

    verdict: Normalized
    remaining_rounds_estimate: int = 0
    milestone_reachable: bool = False
    reason: str = ""

    @classmethod
    def from_dict(cls, raw: dict) -> "SelfAssessment":
        """Parse a raw dict; raises ValueError if verdict is not parseable."""
        verdict = str(raw.get("verdict", "")).strip().upper()
        if verdict not in ("CONTINUE", "ROTATE", "HANDOFF_NOW"):
            raise ValueError(f"unparseable self-assessment verdict: {verdict!r}")
        try:
            remaining = int(raw.get("remaining_rounds_estimate", 0))
        except (TypeError, ValueError):
            remaining = 0
        return cls(
            verdict=verdict,
            remaining_rounds_estimate=max(0, remaining),
            milestone_reachable=bool(raw.get("milestone_reachable", False)),
            reason=str(raw.get("reason", ""))[:200],
        )


@dataclass
class RolePolicy:
    """Programmable strategy for one role's session lifecycle.

    This is the unit users program: they can subclass/parametrize it (or provide
    their own object implementing the same contract) to change thresholds,
    handoff messages, and rotation decisions. Developer and reviewer instances
    differ only in their field values / logic.
    """

    # -- thresholds (fraction of context budget) -----------------------------
    context_threshold_normal: float = 0.4  # start self-assessment
    context_threshold_urgent: float = 0.7  # after stopping work, must hand off

    # -- self-assessment cash --------------------------------
    self_assess_system_prompt: str = (
        "You are a session that tracks its own context usage. Your context "
        "window is filling. Assess whether you should continue, rotate to a "
        "fresh session, or hand off now. Return STRICT JSON only:\n"
        '{"verdict":"CONTINUE|ROTATE|HANDOFF_NOW",'
        '"remaining_rounds_estimate":<int>,"milestone_reachable":<bool>,'
        '"reason":"1-2 sentences"}'
    )

    # -- handoff message templates -------------------------------------------
    handoff_normal_template: str = (
        "你当前的上下文已使用 {usage:.0%}。请为下一个会话撰写交接文档，"
        "记录：当前里程碑、已完成工作、下一步、待决点、约束。"
    )
    handoff_urgent_template: str = (
        "紧急：你的上下文已使用 {usage:.0%}，达到紧急阈值。当前工作结束后必须立刻"
        "交接。请立即撰写紧急交接文档（比正常交接更精简，只保留关键状态与下一步）。"
    )

    # -- flow transition (v4) ------------------------------------------------
    # How this role's session should be handled when the flow advances to a
    # different node. Default REUSE (context persists across nodes for the same
    # role). A user may override on_node_transition for per-node/per-role logic.
    transition_mode: TransitionDecision = TransitionDecision.REUSE

    def on_node_transition(
        self,
        prev_node: str,
        next_node: str,
        ctx: dict | None = None,
    ) -> TransitionDecision:
        """Decide how this role's session is handled on a node transition.

        This is the "flow strategy" folded into the role policy (no standalone
        FlowStrategy interface). The kernel calls it when advancing from
        prev_node to next_node; the returned decision tells the kernel whether
        to reuse, rotate, or pin this role's session as an anchor.

        Default behaviour follows `transition_mode`; users may override this
        method for arbitrary per-node logic.
        """
        return self.transition_mode

    # -- decision logic ------------------------------------------------------

    def should_self_assess(self, usage: float) -> bool:
        """Whether the session should be asked to self-assess at this usage."""
        return usage >= self.context_threshold_normal

    def is_urgent(self, usage: float) -> bool:
        """Whether usage is at/above the urgent (hard) threshold."""
        return usage >= self.context_threshold_urgent

    def handoff_message(self, kind: str, usage: float) -> str:
        """The handoff prompt for a given kind ('normal' | 'urgent')."""
        if kind == "urgent":
            return self.handoff_urgent_template.format(usage=usage)
        return self.handoff_normal_template.format(usage=usage)

    def decide_from_assessment(
        self, assessment: SelfAssessment, usage: float
    ) -> Normalized:
        """Combine the model's self-assessment with the policy's hard rules.

        Returns the final action. The policy can override the model's verdict
        (e.g. force HANDOFF_NOW at the urgent threshold regardless of what the
        model said).
        """
        if self.is_urgent(usage):
            return "HANDOFF_NOW"
        return assessment.verdict


# -- default policies ---------------------------------------------------------

# Workspace directory conventions (v3 role visibility).
# The developer works only inside `code/`; the reviewer works at the work root
# and also sees `handoff/`. Implemented via opencode session directory (the
# session starts at its working directory). Adjusting the worker's mount to
# enforce physical isolation is deferred to a worker rebuild.
WORKSPACE_CONVENTIONS = {
    "developer": {
        "work_dir": "code",
        "visible": ["code"],
        "writable": ["code"],
    },
    "reviewer": {
        "work_dir": ".",
        "visible": [".", "code", "handoff"],
        "writable": ["handoff"],
    },
}


def developer_policy() -> RolePolicy:
    """Default developer policy (permissive thresholds)."""
    return RolePolicy(
        context_threshold_normal=0.4,
        context_threshold_urgent=0.7,
    )


def reviewer_policy() -> RolePolicy:
    """Default reviewer policy (stricter thresholds than developer)."""
    return RolePolicy(
        context_threshold_normal=0.3,
        context_threshold_urgent=0.6,
    )