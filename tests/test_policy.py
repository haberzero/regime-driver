"""Tests for the role policy (session lifecycle strategy)."""

import pytest

from regime_driver.core.policy import (
    SelfAssessment,
    TransitionDecision,
    RolePolicy,
    developer_policy,
    reviewer_policy,
)


def test_self_assessment_parse_ok():
    a = SelfAssessment.from_dict({"verdict": "ROTATE", "remaining_rounds_estimate": 3,
                                  "milestone_reachable": True, "reason": "done"})
    assert a.verdict == "ROTATE"
    assert a.remaining_rounds_estimate == 3
    assert a.milestone_reachable is True


def test_self_assessment_case_insensitive():
    a = SelfAssessment.from_dict({"verdict": "continue"})
    assert a.verdict == "CONTINUE"


def test_self_assessment_unparseable():
    with pytest.raises(ValueError):
        SelfAssessment.from_dict({"verdict": "garbage"})


def test_developer_policy_thresholds():
    p = developer_policy()
    assert p.context_threshold_normal == 0.4
    assert p.context_threshold_urgent == 0.7
    assert not p.should_self_assess(0.3)
    assert p.should_self_assess(0.4)
    assert p.is_urgent(0.7)
    assert not p.is_urgent(0.6)


def test_reviewer_policy_stricter():
    p = reviewer_policy()
    assert p.context_threshold_normal == 0.3
    assert p.context_threshold_urgent == 0.6
    # reviewer self-assesses earlier than developer
    assert p.should_self_assess(0.35)
    assert not developer_policy().should_self_assess(0.35)


def test_decide_from_assessment_continues():
    p = developer_policy()
    a = SelfAssessment("CONTINUE", milestone_reachable=False)
    assert p.decide_from_assessment(a, usage=0.5) == "CONTINUE"


def test_decide_urgent_overrides():
    """At urgent threshold, policy forces HANDOFF_NOW regardless of model."""
    p = developer_policy()
    a = SelfAssessment("CONTINUE", milestone_reachable=False)
    assert p.decide_from_assessment(a, usage=0.8) == "HANDOFF_NOW"


def test_handoff_message_templates_differ():
    p = developer_policy()
    normal = p.handoff_message("normal", 0.5)
    urgent = p.handoff_message("urgent", 0.8)
    assert "紧急" in urgent
    assert "紧急" not in normal
    assert "50%" in normal
    assert "80%" in urgent


def test_default_transition_is_reuse():
    p = developer_policy()
    assert p.on_node_transition("design", "implement") == TransitionDecision.REUSE


def test_custom_transition_policy():
    class PerNode(RolePolicy):
        def on_node_transition(self, prev_node, next_node, ctx=None):
            return TransitionDecision.ROTATE
    p = PerNode()
    assert p.on_node_transition("a", "b") == TransitionDecision.ROTATE


def test_transition_mode_field():
    p = RolePolicy(transition_mode=TransitionDecision.ANCHOR)
    assert p.on_node_transition("a", "b") == TransitionDecision.ANCHOR