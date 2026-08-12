"""Session cleanup policy (L2 resource governance).

The worker accumulates session records over long runs (each drive creates
developer+reviewer sessions). opencode 1.18.11 supports true deletion via
``DELETE /session/{id}`` (verified 2026-08-12) — not just abort.

This module implements a **user-configurable cleanup policy** (a reference model,
NOT enforced by default). The operator opts in via the ``session_cleanup_policy``
setting (a JSON string):

    {"max_sessions": 100, "min_age_sec": 3600, "only_idle": true}

Semantics:
    * ``max_sessions`` (int): when the worker's accumulated session count exceeds
      this, delete enough oldest idle sessions to bring it back to this value.
    * ``min_age_sec`` (int): only delete sessions older than this many seconds
      (0 = any age).
    * ``only_idle`` (bool, default true): the default safety posture.
      **Safety floor (never configurable away)**: a session currently in the
      worker's busy status map is NEVER deleted — deleting an in-flight session
      would 404 the next send_message and break that run.

Design rules:
    * Deterministic, pure: ``plan_cleanup`` returns a list of session ids to
      delete given the policy + the worker's session list — no I/O, fully testable.
    * Safe default: empty/None policy or missing keys = no-op.
    * Idempotent: running it twice deletes nothing the second time.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class CleanupPolicy:
    """Parsed session-cleanup policy (all fields optional; empty = disabled)."""

    max_sessions: int | None = None
    min_age_sec: int = 0
    only_idle: bool = True
    enabled: bool = False

    @classmethod
    def from_config(cls, raw: str | None) -> "CleanupPolicy":
        """Parse a ``session_cleanup_policy`` value (JSON string or None)."""
        if not raw:
            return cls(enabled=False)
        try:
            data = json.loads(raw)
        except (TypeError, ValueError):
            return cls(enabled=False)
        if not isinstance(data, dict):
            return cls(enabled=False)
        max_sessions = data.get("max_sessions")
        # bools are ints in Python; `"max_sessions": true` must NOT enable a
        # near-total teardown. Require an actual int.
        if type(max_sessions) is not int or max_sessions <= 0:
            return cls(enabled=False)
        min_age = data.get("min_age_sec", 0)
        if type(min_age) is not int or min_age < 0:
            min_age = 0
        only_idle = data.get("only_idle", True)
        if not isinstance(only_idle, bool):
            only_idle = True
        return cls(
            max_sessions=max_sessions,
            min_age_sec=min_age,
            only_idle=only_idle,
            enabled=True,
        )

    def to_dict(self) -> dict:
        return {
            "enabled": self.enabled,
            "max_sessions": self.max_sessions,
            "min_age_sec": self.min_age_sec,
            "only_idle": self.only_idle,
        }


@dataclass
class CleanupResult:
    """Outcome of running a cleanup policy."""

    policy: CleanupPolicy
    scanned: int = 0
    eligible: int = 0
    deleted: list[str] = field(default_factory=list)
    deleted_count: int = 0
    skipped_busy: int = 0
    skipped_young: int = 0

    def to_dict(self) -> dict:
        return {
            "enabled": self.policy.enabled,
            "max_sessions": self.policy.max_sessions,
            "scanned": self.scanned,
            "eligible": self.eligible,
            "deleted": self.deleted,
            "deleted_count": self.deleted_count,
            "skipped_busy": self.skipped_busy,
            "skipped_young": self.skipped_young,
        }


def _session_age_sec(session: dict, now: float) -> int | None:
    """Age (seconds) of a session from its ``time.created`` millis, or None."""
    t = (session.get("time") or {})
    created = t.get("created")
    if not isinstance(created, (int, float)):
        return None
    return max(0, int(now - created / 1000.0))


def plan_cleanup(sessions: list[dict], policy: CleanupPolicy,
                 now: float | None = None,
                 busy_ids: set[str] | None = None) -> CleanupResult:
    """Compute which sessions to delete under the policy (pure, no I/O).

    Args:
        sessions: the worker's session list (from ``list_sessions()``).
        policy: parsed policy; ``enabled=False`` -> no-op.
        now: wall time (seconds); defaults to ``time.time()``.
        busy_ids: session ids currently busy; those are never eligible.

    Returns:
        CleanupResult with the sorted list of ids to delete (oldest first).
    """
    result = CleanupResult(policy=policy)
    if not policy.enabled or not sessions:
        return result
    now = now if now is not None else time.time()
    busy_ids = busy_ids or set()

    result.scanned = len(sessions)
    # only consider deletion when we are over the cap; keep the newest
    # (``max_sessions``) sessions, delete the oldest excess ones.
    over = len(sessions) - policy.max_sessions
    if over <= 0:
        return result

    # SAFETY FLOOR (independent of only_idle): a session the driver is actively
    # using is NEVER eligible — deleting an in-flight/referenced session would
    # 404 the next send_message and break that run. only_idle is the default
    # posture; busy_ids from the live status map is the enforced subset.
    candidates: list[tuple[int, str]] = []  # (age, session_id)
    for s in sessions:
        sid = s.get("id")
        if not sid:
            result.skipped_busy += 1  # unknown identity = not deletable
            continue
        if sid in busy_ids:
            result.skipped_busy += 1
            continue
        age = _session_age_sec(s, now)
        if age is None:
            age = 0
        if policy.min_age_sec and age < policy.min_age_sec:
            result.skipped_young += 1
            continue
        candidates.append((age, sid))

    candidates.sort(key=lambda pair: pair[0], reverse=True)  # oldest first
    to_delete = [sid for _, sid in candidates[:over]]
    result.eligible = len(to_delete)
    result.deleted = to_delete
    result.deleted_count = len(to_delete)
    return result


def run_cleanup(client, sessions: list[dict], policy: CleanupPolicy,
                now: float | None = None, busy_ids: set[str] | None = None) -> CleanupResult:
    """Plan + execute the cleanup against a live client (delete eligible sessions).

    Best-effort: a failed delete is logged and skipped, never raises.
    Returns the result (``deleted`` lists actually-deleted ids).
    """
    plan = plan_cleanup(sessions, policy, now=now, busy_ids=busy_ids)
    actually = []
    for sid in plan.deleted:
        try:
            client.delete_session(sid)
            actually.append(sid)
        except Exception as exc:  # noqa: BLE001 — cleanup is best-effort
            logging.getLogger(__name__).warning(
                "session cleanup: delete %s failed: %s", sid, exc)
    plan.deleted = actually
    plan.deleted_count = len(actually)
    return plan
