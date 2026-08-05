"""Tests for session lifecycle (brain-capacity management)."""

from regime_driver.app.session_lifecycle import SessionLifecycle, SessionRotator
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
        self.sent.append((sid, text[:30], agent))


def make_settings(limit=1000, check_every=5):
    return Settings(context_limit_tokens=limit, context_check_every=check_every)


def test_capacity_used():
    client = FakeClient(tokens=(600, 300))
    lc = SessionLifecycle(make_settings(limit=1000), client)
    st = SessionState(SessionKind.DEVELOPER, "s1")
    assert round(lc.capacity_used(st), 6) == 0.9


def test_near_limit():
    lc = SessionLifecycle(make_settings(limit=1000), FakeClient(tokens=(1000, 0)))
    st = SessionState(SessionKind.DEVELOPER, "s1")
    assert lc.near_limit(st)


def test_not_near_limit():
    lc = SessionLifecycle(make_settings(limit=1000), FakeClient(tokens=(100, 0)))
    st = SessionState(SessionKind.DEVELOPER, "s1")
    assert not lc.near_limit(st)


def test_should_check_every_n():
    lc = SessionLifecycle(make_settings(check_every=5), FakeClient())
    st = SessionState(SessionKind.DEVELOPER, "s1")
    for _ in range(4):
        st.advance_round()
    assert not lc.should_check(st)  # round=4, not multiple of 5
    st.advance_round()  # round=5
    assert lc.should_check(st)


def test_rotate_with_handover():
    client = FakeClient(session_id_for="dev")
    sessions = FakeSessions(client)
    rotator = SessionRotator(client, sessions)
    new = rotator.rotate_with_handover(SessionKind.DEVELOPER, "做了X", ["禁push"])
    assert new.session_id == "dev1"
    assert "做了X" in sessions.sent[0][1]


class FakeSessions:
    def __init__(self, client):
        self.client = client
        self.sent = []
        self.developer = None

    def rotate_session(self, kind, inject=None):
        if kind == SessionKind.DEVELOPER:
            self.developer = SessionState(kind, self.client.create_session("regime-driver"))
            if inject:
                self.sent.append((self.developer.session_id, inject, "developer"))
            return self.developer
        raise ValueError("only developer in test")