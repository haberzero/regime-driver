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

    def rotate_session(self, kind: SessionKind, inject: str | None = None) -> SessionState:
        """Rotate a session: create a fresh one, optionally inject a handover.

        Returns the new SessionState. The old session is left on the server for
        audit (not force-deleted); only the managed reference moves to the new id.
        """
        if kind == SessionKind.DEVELOPER:
            self.developer = SessionState(kind, self.client.create_session("regime-driver"))
            state = self.developer
        elif kind == SessionKind.REVIEWER:
            self.reviewer = SessionState(kind, self.client.create_session("regime-reviewer"))
            state = self.reviewer
        else:
            raise ValueError(f"unknown session kind: {kind}")
        if inject:
            agent = self.developer_agent if kind == SessionKind.DEVELOPER else self.reviewer_agent
            self.client.send_message(state.session_id, inject, agent)
        return state

    def all_session_ids(self) -> list[str]:
        """All managed session ids (for the monitor thread to watch)."""
        ids: list[str] = []
        for state in (self.developer, self.reviewer):
            if state is not None and state.session_id:
                ids.append(state.session_id)
        return ids