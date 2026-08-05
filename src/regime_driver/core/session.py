"""Session state model (pure domain logic).

A session is the private brain capacity of a role. The kernel does not care
which role it is — roles are user-registered instances. This module tracks a
session's round count and turn-check cadence only.
"""

from __future__ import annotations

# Convenience role ids (user may register any other role id).
DEVELOPER = "developer"
REVIEWER = "reviewer"


class SessionState:
    """Mutable state for one opencode session."""

    def __init__(self, role: str, session_id: str | None = None) -> None:
        self.role = role
        self.session_id = session_id
        self.round = 0

    def advance_round(self) -> int:
        self.round += 1
        return self.round

    def turn_check_due(self, check_every: int) -> bool:
        """True when the current round is a multiple of check_every."""
        return check_every > 0 and self.round > 0 and self.round % check_every == 0

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return (
            f"SessionState(role={self.role}, sid={self.session_id}, "
            f"round={self.round})"
        )