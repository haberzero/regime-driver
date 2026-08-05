"""Tests for session lifecycle (policy-driven brain-capacity management)."""

from regime_driver.app.session_lifecycle import SessionLifecycle, SessionRotator
from regime_driver.core.handoff import Handoff
from regime_driver.core.policy import SelfAssessment, developer_policy, reviewer_policy
from regime_driver.core.session import SessionKind, SessionState
from regime_driver.infra.settings import Settings


class FakeClient:
    def __init__(self, tokens=(0, 0), session_id_for="x"):
        self.tokens = tokens
        self.created = []
        self.sent = []
        self.session_id_for = session_id_for

    def session_tokens(self, sid):
        return self.tokens

    def create_session(self, title):
        self.created.append(title)
        return f"{self.session_id_for}{len(self.created)}"

    def send_message(self, sid, text, agent):
        self.sent.append((sid, text[:40], agent))

    def ask_and_get_text(self, sid, prompt, agent, model=None):
        return '{"verdict":"ROTATE","remaining_rounds_estimate":2,"milestone_reachable":true,"reason":"ok"}'

    def delete_session(self, sid):
        pass


def make_settings(limit=1000):
    return Settings(context_limit_tokens=limit)


def test_capacity_used():
    client = FakeClient(tokens=(600, 300))
    lc = SessionLifecycle(make_settings(limit=1000), client, developer_policy())
    st = SessionState(SessionKind.DEVELOPER, "s1")
    assert round(lc.capacity_used(st), 6) == 0.9


def test_should_self_assess_below_threshold():
    lc = SessionLifecycle(make_settings(limit=1000), FakeClient(tokens=(100, 0)), developer_policy())
    st = SessionState(SessionKind.DEVELOPER, "s1")
    assert not lc.should_self_assess(st)  # 10% < 40%


def test_should_self_assess_at_threshold():
    lc = SessionLifecycle(make_settings(limit=1000), FakeClient(tokens=(400, 0)), developer_policy())
    st = SessionState(SessionKind.DEVELOPER, "s1")
    assert lc.should_self_assess(st)  # 40%


def test_is_urgent():
    lc = SessionLifecycle(make_settings(limit=1000), FakeClient(tokens=(700, 0)), developer_policy())
    st = SessionState(SessionKind.DEVELOPER, "s1")
    assert lc.is_urgent(st)
    lc2 = SessionLifecycle(make_settings(limit=1000), FakeClient(tokens=(600, 0)), developer_policy())
    assert not lc2.is_urgent(SessionState(SessionKind.DEVELOPER, "s1"))


def test_reviewer_policy_stricter():
    """Reviewer self-assesses at a lower threshold than developer."""
    dev = SessionLifecycle(make_settings(), FakeClient(tokens=(350, 0)), developer_policy())
    rev = SessionLifecycle(make_settings(), FakeClient(tokens=(350, 0)), reviewer_policy())
    assert not dev.should_self_assess(SessionState(SessionKind.DEVELOPER, "s1"))
    assert rev.should_self_assess(SessionState(SessionKind.REVIEWER, "s1"))


def test_decide_urgent_forces_handoff():
    lc = SessionLifecycle(make_settings(limit=1000), FakeClient(tokens=(800, 0)), developer_policy())
    st = SessionState(SessionKind.DEVELOPER, "s1")
    assessment = SelfAssessment("CONTINUE", milestone_reachable=False)
    assert lc.decide(st, assessment) == "handoff_now"


def test_decide_follows_assessment():
    lc = SessionLifecycle(make_settings(limit=1000), FakeClient(tokens=(500, 0)), developer_policy())
    st = SessionState(SessionKind.DEVELOPER, "s1")
    assert lc.decide(st, SelfAssessment("ROTATE")) == "rotate"
    assert lc.decide(st, SelfAssessment("CONTINUE")) == "continue"


def test_rotate_with_handover_normal():
    client = FakeClient(session_id_for="dev")
    sessions = FakeSessions(client)
    rotator = SessionRotator(client, sessions)
    new = rotator.rotate_with_handover(SessionKind.DEVELOPER, "做了X", ["禁push"])
    assert new.session_id == "dev1"
    assert '"kind":"brain_normal"' in sessions.sent[0][1]


def test_rotate_with_handover_urgent():
    client = FakeClient(session_id_for="rev")
    sessions = FakeSessions(client)
    rotator = SessionRotator(client, sessions)
    new = rotator.rotate_with_handover(SessionKind.REVIEWER, "紧急", handoff_kind="urgent")
    assert new.session_id == "rev1"
    assert '"kind":"brain_urgent"' in sessions.sent[0][1]


class FakeSessions:
    def __init__(self, client):
        self.client = client
        self.sent = []
        self.developer = None
        self.reviewer = None

    def rotate_session(self, kind, inject=None):
        if kind == SessionKind.DEVELOPER:
            self.developer = SessionState(kind, self.client.create_session("regime-driver"))
            if inject:
                self.sent.append((self.developer.session_id, inject, "developer"))
            return self.developer
        if kind == SessionKind.REVIEWER:
            self.reviewer = SessionState(kind, self.client.create_session("regime-reviewer"))
            if inject:
                self.sent.append((self.reviewer.session_id, inject, "reviewer"))
            return self.reviewer
        raise ValueError("only developer/reviewer in test")