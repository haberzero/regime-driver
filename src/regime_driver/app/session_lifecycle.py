"""Session lifecycle (app layer): policy-driven brain-capacity management.

Roles are independent individuals with a PRIVATE session memory. Per v3/v4, the
robot asks the session to self-assess and combines that with the role's policy.
The kernel works by role id; each role's policy comes from the RoleRegistry.
"""

from __future__ import annotations

from ..core.handoff import Handoff
from ..core.policy import RolePolicy, SelfAssessment
from ..core.role import RoleRegistry
from ..core.session import SessionState
from ..infra.opencode import OpenCodeClient
from ..infra.settings import Settings
from .self_assess import SelfAssessor


class SessionLifecycle:
    """Detects near-limit sessions and drives self-assessment + rotation."""

    def __init__(
        self,
        settings: Settings,
        client: OpenCodeClient,
        roles: RoleRegistry,
    ) -> None:
        self.settings = settings
        self.client = client
        self.roles = roles
        self._assessors: dict[str, SelfAssessor] = {}

    def policy_for(self, role_id: str) -> RolePolicy:
        return self.roles.get(role_id).policy

    def _ensure_assessor(self, role_id: str) -> SelfAssessor:
        if role_id not in self._assessors:
            role = self.roles.get(role_id)
            self._assessors[role_id] = SelfAssessor(
                self.settings, self.client, role.policy, role.agent
            )
        return self._assessors[role_id]

    def capacity_used(self, state: SessionState) -> float:
        """Fraction of the context budget used (0..1+, 0 if unknown)."""
        reasoning, output = self.client.session_tokens(state.session_id or "")
        total = reasoning + output
        limit = self.settings.context_limit_tokens
        return total / limit if limit else 0.0

    def should_self_assess(self, state: SessionState) -> bool:
        return self.policy_for(state.role).should_self_assess(self.capacity_used(state))

    def is_urgent(self, state: SessionState) -> bool:
        return self.policy_for(state.role).is_urgent(self.capacity_used(state))

    def assess(self, state: SessionState, usage: float | None = None) -> "SelfAssessment | None":
        if usage is None:
            usage = self.capacity_used(state)
        if not self.policy_for(state.role).should_self_assess(usage):
            return None
        return self._ensure_assessor(state.role).assess(state)

    def decide(self, state: SessionState, assessment: SelfAssessment | None,
               usage: float | None = None) -> str:
        policy = self.policy_for(state.role)
        if usage is None:
            usage = self.capacity_used(state)
        if assessment is None:
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
        self.sessions = sessions  # SessionRegistry

    def rotate_with_handover(
        self,
        role_id: str,
        summary: str,
        constraints: list[str] | None = None,
        pending: list[str] | None = None,
        handoff_kind: str = "brain_normal",
    ) -> SessionState:
        kind_str = "brain_urgent" if handoff_kind == "urgent" else "brain_normal"
        handoff = Handoff.brain_handoff(kind_str, summary, constraints, pending, role=role_id)
        # WORK_PLAN13: `summary` is the composed opening message for the fresh
        # session (handover document + instruction), so inject it as the session's
        # first message instead of a raw machine JSON blob. The Handoff remains
        # the auditable record for the ledger.
        return self.sessions.rotate(role_id, inject=summary)