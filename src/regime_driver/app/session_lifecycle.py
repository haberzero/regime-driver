"""Session lifecycle (app layer): brain-capacity management.

Roles are independent individuals with a PRIVATE session memory (brain capacity).
This module detects when a session is near its context limit and decides whether
to rotate it (write a handover, open a fresh session, inject the handover).

This embodies the OA principle: "how each person knows when their memory is full
and hands off to a fresh session."
"""

from __future__ import annotations

from ..core.handoff import Handoff
from ..core.session import SessionKind, SessionState
from ..infra.opencode import OpenCodeClient
from ..infra.settings import Settings


class SessionLifecycle:
    """Detects near-limit sessions and performs rotation."""

    def __init__(self, settings: Settings, client: OpenCodeClient) -> None:
        self.settings = settings
        self.client = client

    def capacity_used(self, state: SessionState) -> float:
        """Fraction of the context budget used (0..1+, 0 if unknown)."""
        reasoning, output = self.client.session_tokens(state.session_id or "")
        total = reasoning + output
        limit = self.settings.context_limit_tokens
        return total / limit if limit else 0.0

    def near_limit(self, state: SessionState) -> bool:
        """True when the session's brain capacity is at/above the limit."""
        return self.capacity_used(state) >= 1.0

    def should_check(self, state: SessionState) -> bool:
        """Whether to check capacity this round (every N rounds)."""
        return state.round > 0 and state.round % self.settings.context_check_every == 0


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
    ) -> SessionState:
        """Rotate a session with a handover document injected into the fresh one."""
        handoff = Handoff.session_handover(summary, constraints, pending)
        return self.sessions.rotate_session(kind, inject=handoff.to_json())