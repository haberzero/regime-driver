"""Session management (app layer): lifecycle of developer/reviewer sessions.

Composes the OpenCodeClient (infra) with the SessionState domain model (core)
to create, reuse, round-track, and rotate sessions.
"""

from __future__ import annotations

from ..core.session import SessionKind, SessionState
from ..infra.opencode import OpenCodeClient


class SessionManager:
    """Owns the developer and reviewer sessions."""

    def __init__(
        self,
        client: OpenCodeClient,
        developer_agent: str = "developer",
        reviewer_agent: str = "reviewer",
    ) -> None:
        self.client = client
        self.developer_agent = developer_agent
        self.reviewer_agent = reviewer_agent
        self.developer: SessionState | None = None
        self.reviewer: SessionState | None = None

    # -- developer ----------------------------------------------------------

    def ensure_developer(self, title: str = "regime-driver") -> SessionState:
        """Create the developer session if not present; reuse otherwise."""
        if self.developer is None:
            sid = self.client.create_session(title)
            self.developer = SessionState(SessionKind.DEVELOPER, sid)
        return self.developer

    # -- reviewer -----------------------------------------------------------

    def ensure_reviewer(self, title: str = "regime-reviewer") -> SessionState:
        """Create the reviewer session if not present; reuse otherwise (M-3)."""
        if self.reviewer is None:
            sid = self.client.create_session(title)
            self.reviewer = SessionState(SessionKind.REVIEWER, sid)
        return self.reviewer

    # -- round / health -----------------------------------------------------

    def advance_developer_round(self) -> int:
        if self.developer is None:
            raise RuntimeError("developer session not created")
        return self.developer.advance_round()

    def developer_turn_check_due(self, check_every: int) -> bool:
        if self.developer is None:
            return False
        return self.developer.turn_check_due(check_every)

    def abort_developer(self) -> None:
        if self.developer is not None and self.developer.session_id:
            self.client.abort_session(self.developer.session_id)