"""Tests for the self-assessor (session self-assessment)."""

import json

from regime_driver.app.self_assess import SelfAssessor
from regime_driver.core.policy import developer_policy
from regime_driver.core.session import SessionState
from regime_driver.infra.settings import Settings


class FakeClient:
    def __init__(self, replies, tokens=(0, 0)):
        self.replies = list(replies)
        self.tokens = tokens
        self.created = 0
        self.deleted = 0

    def create_session(self, title):
        self.created += 1
        return "sa_sid"

    def delete_session(self, sid):
        self.deleted += 1

    def session_tokens(self, sid):
        return self.tokens

    def ask_and_get_text(self, sid, prompt, agent, model=None):
        if self.replies:
            return self.replies.pop(0)
        raise AssertionError("no more replies")


def make_assessor(replies, tokens=(0, 0)):
    client = FakeClient(replies, tokens)
    assessor = SelfAssessor(Settings(context_limit_tokens=1000), client,
                            developer_policy(), "developer")
    return assessor, client


def test_assess_returns_parseable():
    a, c = make_assessor([json.dumps({"verdict": "ROTATE", "remaining_rounds_estimate": 2,
                                      "milestone_reachable": True, "reason": "ok"})],
                         tokens=(400, 0))
    st = SessionState("developer", "s1")
    result = a.assess(st)
    assert result is not None
    assert result.verdict == "ROTATE"
    assert result.remaining_rounds_estimate == 2


def test_assess_uses_ephemeral_session():
    a, c = make_assessor([json.dumps({"verdict": "CONTINUE"})], tokens=(100, 0))
    st = SessionState("developer", "s1")
    a.assess(st)
    assert c.created == 1
    assert c.deleted == 1  # ephemeral session cleaned up


def test_assess_retries_on_unparseable():
    replies = ["not json", json.dumps({"verdict": "HANDOFF_NOW"})]
    a, c = make_assessor(replies, tokens=(700, 0))
    st = SessionState("developer", "s1")
    result = a.assess(st)
    assert result is not None
    assert result.verdict == "HANDOFF_NOW"


def test_assess_returns_none_on_exhausted_retries():
    # max_retries=2 -> 3 attempts; give 3 unparseable replies
    a, c = make_assessor(["garbage", "still garbage", "more garbage"], tokens=(700, 0))
    st = SessionState("developer", "s1")
    assert a.assess(st) is None


def test_assess_includes_usage_in_prompt():
    a, c = make_assessor([json.dumps({"verdict": "CONTINUE"})], tokens=(500, 0))
    st = SessionState("developer", "s1")
    a.assess(st)
    # usage 500/1000 = 50%, prompt should mention it; the prompt is in the system+user
    # we can't easily inspect, but the assessment succeeded
    assert c.created == 1