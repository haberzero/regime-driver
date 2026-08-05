"""Tests for session lifecycle (policy-driven brain-capacity management)."""

from regime_driver.app.session_lifecycle import SessionLifecycle, SessionRotator
from regime_driver.core.policy import SelfAssessment
from regime_driver.core.role import Role, RoleRegistry, default_roles
from regime_driver.core.session import SessionState
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


def make_lifecycle(tokens=(0, 0), roles=None):
    client = FakeClient(tokens=tokens)
    lc = SessionLifecycle(make_settings(), client, roles or default_roles())
    return lc, client


def test_capacity_used():
    lc, _ = make_lifecycle(tokens=(600, 300))
    st = SessionState("developer", "s1")
    assert round(lc.capacity_used(st), 6) == 0.9


def test_should_self_assess_below_threshold():
    lc, _ = make_lifecycle(tokens=(100, 0))
    assert not lc.should_self_assess(SessionState("developer", "s1"))


def test_should_self_assess_at_threshold():
    lc, _ = make_lifecycle(tokens=(400, 0))
    assert lc.should_self_assess(SessionState("developer", "s1"))


def test_is_urgent():
    lc, _ = make_lifecycle(tokens=(700, 0))
    assert lc.is_urgent(SessionState("developer", "s1"))
    lc2, _ = make_lifecycle(tokens=(600, 0))
    assert not lc2.is_urgent(SessionState("developer", "s1"))


def test_reviewer_policy_stricter():
    """Reviewer self-assesses at a lower threshold than developer."""
    roles = default_roles()
    dev_lc, _ = make_lifecycle(tokens=(350, 0), roles=roles)
    rev_lc, _ = make_lifecycle(tokens=(350, 0), roles=roles)
    assert not dev_lc.should_self_assess(SessionState("developer", "s1"))
    assert rev_lc.should_self_assess(SessionState("reviewer", "s1"))


def test_decide_urgent_forces_handoff():
    lc, _ = make_lifecycle(tokens=(800, 0))
    st = SessionState("developer", "s1")
    assessment = SelfAssessment("CONTINUE", milestone_reachable=False)
    assert lc.decide(st, assessment) == "handoff_now"


def test_decide_follows_assessment():
    lc, _ = make_lifecycle(tokens=(500, 0))
    st = SessionState("developer", "s1")
    assert lc.decide(st, SelfAssessment("ROTATE")) == "rotate"
    assert lc.decide(st, SelfAssessment("CONTINUE")) == "continue"


def test_rotate_with_handover_normal():
    client = FakeClient(session_id_for="dev")
    sessions = FakeSessions(client)
    rotator = SessionRotator(client, sessions)
    new = rotator.rotate_with_handover("developer", "做了X", ["禁push"])
    assert new.session_id == "dev1"
    assert '"kind":"brain_normal"' in sessions.sent[0][1]


def test_rotate_with_handover_urgent():
    client = FakeClient(session_id_for="rev")
    sessions = FakeSessions(client)
    rotator = SessionRotator(client, sessions)
    new = rotator.rotate_with_handover("reviewer", "紧急", handoff_kind="urgent")
    assert new.session_id == "rev1"
    assert '"kind":"brain_urgent"' in sessions.sent[0][1]


def test_custom_role_in_registry():
    roles = RoleRegistry().register(
        Role(id="auditor", agent="auditor", policy=__import__(
            "regime_driver.core.policy", fromlist=["developer_policy"]).developer_policy())
    )
    assert roles.has("auditor")
    assert roles.get("auditor").agent == "auditor"


class FakeSessions:
    def __init__(self, client):
        self.client = client
        self.sent = []
        self.states = {}

    def rotate(self, role_id, inject=None):
        state = SessionState(role_id, self.client.create_session(f"regime-{role_id}"))
        if inject:
            self.sent.append((state.session_id, inject, role_id))
        return state