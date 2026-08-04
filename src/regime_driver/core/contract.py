"""Deterministic gate for the reviewer JSON contract (DESIGN §4.2).

Pure function: validates a ReviewerVerdict against allowed sets, required
field linkage, confidence bounds, and verdict/action consistency. No I/O.
"""

from __future__ import annotations

from .models import (
    Action,
    GateResult,
    ReviewerVerdict,
    Verdict,
)

# action -> allowed verdicts (consistency)
ACTION_VERDICT_OK: dict[Action, set[Verdict]] = {
    "ask_developer": {"issue_pending", "issue_resolved", "advance"},
    "request_context": {"blocked", "issue_pending"},
    "advance": {"issue_resolved", "advance"},
    "abort_session": {"blocked", "issue_pending"},
    "report_user": {"blocked", "human_escalate"},
}

# per-action minimum confidence (destructive/heavy actions demand higher proof)
ACTION_CONF_MIN: dict[Action, float] = {
    "ask_developer": 0.0,
    "request_context": 0.0,
    "advance": 0.5,
    "abort_session": 0.7,
    "report_user": 0.7,
}


class ContractError(Exception):
    """Raised when the verdict is structurally invalid (pre-validation)."""


def gate_reviewer_verdict(
    verdict: ReviewerVerdict,
    valid_node_ids: set[str] | None = None,
) -> GateResult:
    """Validate a reviewer verdict against the deterministic gate.

    Args:
        verdict: the parsed reviewer verdict.
        valid_node_ids: optional set of valid next-state node ids; if provided,
            advance actions must name a state in this set.

    Returns:
        GateResult with ok=True and the normalized verdict, or ok=False plus a
        human-readable reason.
    """
    # 1. field whitelist (enforced by the Literal types on model construction)
    action = verdict.action
    v_action = verdict.verdict

    # 2. required field linkage
    if action == "ask_developer" and not (verdict.message_to_developer or "").strip():
        return GateResult(ok=False, reason="ask_developer requires message_to_developer")
    if action == "advance":
        ns = verdict.next_state
        if not ns:
            return GateResult(ok=False, reason="advance requires next_state")
        if valid_node_ids is not None and ns not in valid_node_ids:
            return GateResult(
                ok=False,
                reason=f"advance next_state '{ns}' not in state machine",
            )
    if action == "request_context" and not (verdict.context_requested or "").strip():
        return GateResult(ok=False, reason="request_context requires context_requested")

    # 3. confidence bound (already enforced by model, double-checked here)
    if not (0.0 <= verdict.confidence <= 1.0):
        return GateResult(ok=False, reason="confidence out of [0,1]")
    if verdict.confidence < ACTION_CONF_MIN[action]:
        return GateResult(
            ok=False,
            reason=f"confidence {verdict.confidence} < min {ACTION_CONF_MIN[action]} for {action}",
        )

    # 4. verdict/action consistency
    if v_action not in ACTION_VERDICT_OK[action]:
        return GateResult(
            ok=False,
            reason=f"verdict '{v_action}' inconsistent with action '{action}'",
        )

    return GateResult(ok=True, reason="ok", verdict=verdict)


def parse_reviewer_verdict(raw: dict) -> ReviewerVerdict:
    """Best-effort parse of a raw dict into a ReviewerVerdict.

    Raises ContractError on structural failure (missing field / bad literal).
    The caller catches this and treats it as a gate rejection.
    """
    try:
        return ReviewerVerdict.model_validate(raw)
    except Exception as exc:  # pydantic ValidationError
        raise ContractError(str(exc)) from exc