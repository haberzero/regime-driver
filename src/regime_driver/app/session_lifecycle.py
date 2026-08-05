"""Session lifecycle (app layer): policy-driven brain-capacity management.

Roles are independent individuals with a PRIVATE session memory. Per v3, the
robot does NOT hard-decide capacity; it asks the session to self-assess and
combines that with the role policy's thresholds:

  - below normal threshold (40%): no check
  - at/above normal (40%): ask the session to self-assess
  - at/above urgent (70%): after the current work stops, MUST hand off urgently

The policy (developer vs reviewer) is programmable and they differ in thresholds.
"""

from __future__ import annotations

from ..core.handoff import Handoff
from ..core.policy import RolePolicy, SelfAssessment, developer_policy, reviewer_policy
from ..core.session import SessionKind, SessionState
from ..infra.opencode import OpenCodeClient
from ..infra.settings import Settings
from .self_assess import SelfAssessor


class SessionLifecycle:
    """Detects near-limit sessions and drives self-assessment + rotation."""

    def __init__(
        self,
        settings: Settings,
        client: OpenCodeClient,
        developer_policy_obj: RolePolicy | None = None,
        reviewer_policy_obj: RolePolicy | None = None,
    ) -> None:
        self.settings = settings
        self.client = client
        self._developer_policy = developer_policy_obj or developer_policy()
        self._reviewer_policy = reviewer_policy_obj or reviewer_policy()
        self._assessors: dict[SessionKind, SelfAssessor] = {}

    def policy_for(self, kind: SessionKind) -> RolePolicy:
        return self._reviewer_policy if kind == SessionKind.REVIEWER else self._developer_policy

    def _ensure_assessor(self, kind: SessionKind) -> SelfAssessor:
        if kind not in self._assessors:
            agent = (self.settings.agent_developer if kind == SessionKind.DEVELOPER
                     else self.settings.agent_reviewer)
            self._assessors[kind] = SelfAssessor(
                self.settings, self.client, self.policy_for(kind), agent
            )
        return self._assessors[kind]

    def capacity_used(self, state: SessionState) -> float:
        """Fraction of the context budget used (0..1+, 0 if unknown)."""
        reasoning, output = self.client.session_tokens(state.session_id or "")
        total = reasoning + output
        limit = self.settings.context_limit_tokens
        return total / limit if limit else 0.0

    def should_self_assess(self, state: SessionState) -> bool:
        """Whether the session should be asked to self-assess (per policy)."""
        return self.policy_for(state.kind).should_self_assess(self.capacity_used(state))

    def is_urgent(self, state: SessionState) -> bool:
        """Whether the session is at/above the urgent (hard) threshold."""
        return self.policy_for(state.kind).is_urgent(self.capacity_used(state))

    def assess(self, state: SessionState, usage: float | None = None) -> "SelfAssessment | None":
        """Ask the session to self-assess (via the policy's threshold)."""
        if usage is None:
            usage = self.capacity_used(state)
        if not self.policy_for(state.kind).should_self_assess(usage):
            return None
        assessor = self._ensure_assessor(state.kind)
        return assessor.assess(state)

    def decide(self, state: SessionState, assessment: SelfAssessment | None,
               usage: float | None = None) -> str:
        """Combine policy + assessment into a final action.

        Delegates to the policy's decide_from_assessment so the policy is the
        single source of decision logic (user-programmable).

        Returns one of: "continue" | "rotate" | "handoff_now".
        """
        policy = self.policy_for(state.kind)
        if usage is None:
            usage = self.capacity_used(state)
        if assessment is None:
            # no self-assessment (below normal threshold or parse failure): only
            # the urgent threshold can force a handoff
            return "handoff_now" if policy.is_urgent(usage) else "continue"
        decision = policy.decide_from_assessment(assessment, usage)
        return {
            "CONTINUE": "continue",
            "ROTATE": "rotate",
            "HANDOFF_NOW": "handoff_now",
        }.get(decision, "continue")


class SessionRotator:
    """Performs a rotation: handover + fresh session + inject."""

    def __init__(self, client: OpenCodeClient, sessions) -> None:
        self.client = client
        self.sessions = sessions  # SessionManager

    def rotate_with_handover(
        self,
        kind: SessionKind,
        summary: str,
        constraints: list[str] | None = None,
        pending: list[str] | None = None,
        handoff_kind: str = "brain_normal",
    ) -> SessionState:
        """Rotate a session with a handover document injected into the fresh one."""
        kind_str = "brain_urgent" if handoff_kind == "urgent" else "brain_normal"
        handoff = Handoff.brain_handoff(kind_str, summary, constraints, pending, role=kind.value)
        return self.sessions.rotate_session(kind, inject=handoff.to_json())