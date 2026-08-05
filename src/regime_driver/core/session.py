"""Session state model (pure domain logic).

Tracks the lifecycle of a developer or reviewer session: round count, health,
and whether a session-turn check is due. No I/O.
"""

from __future__ import annotations

from enum import Enum


class SessionKind(str, Enum):
    DEVELOPER = "developer"
    REVIEWER = "reviewer"


class SessionState:
    """Mutable state for one opencode session."""

    def __init__(self, kind: SessionKind, session_id: str | None = None) -> None:
        self.kind = kind
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
            f"SessionState(kind={self.kind.value}, sid={self.session_id}, "
            f"round={self.round})"
        )