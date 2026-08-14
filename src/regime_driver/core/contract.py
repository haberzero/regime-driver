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
    "ask_human": {"blocked", "issue_pending", "human_escalate"},
}

# per-action minimum confidence (destructive/heavy actions demand higher proof)
ACTION_CONF_MIN: dict[Action, float] = {
    "ask_developer": 0.0,
    "request_context": 0.0,
    "advance": 0.5,
    "abort_session": 0.7,
    "report_user": 0.7,
    "ask_human": 0.6,
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
            advance actions must name a state exactly in this set (no fuzzy match).

    Returns:
        GateResult with ok=True and the verified verdict, or ok=False plus a
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
        # A judge on a TERMINAL node (no successors) advances to "end of flow":
        # next_state must be null AND valid_node_ids must be empty. This is how a
        # final-review judge completes a workflow. Any other null/next mismatch
        # is rejected.
        if valid_node_ids is not None and not valid_node_ids:
            if ns is not None:
                return GateResult(
                    ok=False,
                    reason=f"advance next_state '{ns}' on a terminal node must be null",
                )
        else:
            if not ns:
                return GateResult(ok=False, reason="advance requires next_state")
            if valid_node_ids is not None and ns not in valid_node_ids:
                return GateResult(
                    ok=False,
                    reason=f"advance next_state '{ns}' not in state machine "
                           f"(valid: {sorted(valid_node_ids)})",
                )
    if action == "request_context" and not (verdict.context_requested or "").strip():
        return GateResult(ok=False, reason="request_context requires context_requested")
    if action == "ask_human" and not (verdict.human_question or "").strip():
        return GateResult(ok=False, reason="ask_human requires human_question")

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

    # 5. semantic gate (WORK_PLAN13): a reviewer that documents a blocking issue
    #    must not also wave the work through. The gate is a FORMAT gate plus this
    #    minimal SEMANTIC rule — "advance with unresolved blocking findings" is a
    #    contradiction and is rejected, forcing the reviewer to resolve it or
    #    route back to the developer.
    blocking = [i.summary for i in (verdict.issues or []) if i.severity == "blocking"]
    if action == "advance" and blocking:
        return GateResult(
            ok=False,
            reason=f"advance with {len(blocking)} unresolved blocking issue(s): {blocking}",
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