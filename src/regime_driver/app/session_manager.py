"""Session registry (app layer): manage sessions by arbitrary role id.

The kernel manages sessions keyed by role id; it does not special-case
"developer"/"reviewer". Roles are user-registered (see core/role.py). Each role
owns one active session (its private brain capacity).
"""

from __future__ import annotations

from ..core.session import SessionState
from ..infra.opencode import OpenCodeClient


class SessionRegistry:
    """Owns the active session per role id."""

    def __init__(
        self,
        client: OpenCodeClient,
        agent_by_role: dict[str, str] | None = None,
    ) -> None:
        self.client = client
        self.agent_by_role = agent_by_role or {}
        self._sessions: dict[str, SessionState] = {}

    def register_agent(self, role: str, agent: str) -> None:
        self.agent_by_role[role] = agent

    def agent_for(self, role: str) -> str:
        return self.agent_by_role.get(role, role)

    def ensure(self, role: str, title: str | None = None) -> SessionState:
        """Create the role's session if absent; reuse otherwise."""
        if role not in self._sessions:
            sid = self.client.create_session(title or f"regime-{role}")
            self._sessions[role] = SessionState(role, sid)
        return self._sessions[role]

    def get(self, role: str) -> SessionState | None:
        return self._sessions.get(role)

    def states(self) -> list[SessionState]:
        return list(self._sessions.values())

    def rotate(self, role: str, inject: str | None = None) -> SessionState:
        """Rotate a role's session: create a fresh one, optionally inject."""
        state = SessionState(role, self.client.create_session(f"regime-{role}"))
        self._sessions[role] = state
        if inject:
            self.client.send_message(state.session_id, inject, self.agent_for(role))
        return state

    def abort(self, role: str) -> None:
        state = self._sessions.get(role)
        if state is not None and state.session_id:
            self.client.abort_session(state.session_id)

    def advance_round(self, role: str) -> int:
        state = self._sessions.get(role)
        if state is None:
            raise RuntimeError(f"session for role '{role}' not created")
        return state.advance_round()

    def turn_check_due(self, role: str, check_every: int) -> bool:
        state = self._sessions.get(role)
        return state.turn_check_due(check_every) if state else False

    def all_session_ids(self) -> list[str]:
        return [s.session_id for s in self._sessions.values() if s.session_id]