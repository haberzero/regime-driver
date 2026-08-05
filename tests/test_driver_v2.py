"""Tests for v2 orchestration: multi-round interrogation, convergence, session rotation."""

from regime_driver.app.driver import RegimeDriver
from regime_driver.core.models import Outcome
from regime_driver.infra.regime_loader import load_regime
from regime_driver.infra.settings import Settings


class FakeClient:
    """Minimal client for orchestrator tests (no real opencode)."""

    def __init__(self):
        self.created = 0
        self.sent = []
        self.tokens = (0, 0)

    def create_session(self, title):
        self.created += 1
        return f"ses_{self.created}"

    def send_message(self, sid, text, agent):
        self.sent.append((sid, text[:60], agent))

    def session_tokens(self, sid):
        return self.tokens

    def session_status(self, sid):
        return "idle"

    def read_messages(self, sid):
        return []

    def abort_session(self, sid):
        pass

    def delete_session(self, sid):
        pass


def make_driver(settings_overrides=None):
    overrides = settings_overrides or {}
    s = Settings(**overrides)
    sm = load_regime()
    client = FakeClient()
    return RegimeDriver(s, sm, client), client


class FakeReviewerResult:
    def __init__(self, verdict, action, message="", next_state=None):
        self.ok = True
        self.verdict = type("V", (), {
            "verdict": verdict, "action": action,
            "message_to_developer": message, "next_state": next_state,
            "confidence": 0.9, "reason": "reason",
        })()


def test_multiround_interrogation_converges_on_advance(monkeypatch):
    """A persistent ask -> advance with a changed report should not loop."""
    d, client = make_driver()
    # stub the reviewer and developer nodes
    calls = {"n": 0}

    def fake_judge(node_id, context, developer_report, extra_context, valid_targets, cancel):
        calls["n"] += 1
        if calls["n"] <= 2:
            return FakeReviewerResult("issue_pending", "ask_developer",
                                      message=f"请修复第{calls['n']}轮问题")
        return FakeReviewerResult("advance", "advance", next_state="implement")

    d._get_reviewer = lambda: type("R", (), {"judge": staticmethod(fake_judge)})()
    d._run_developer_node = lambda sid, nid, ctx: (None, f"汇报第{nid}轮")

    # manually drive _run_reviewer_node
    result = d._run_reviewer_node("dev", "design", "ctx", None)
    assert result[0] is None  # no failure
    assert result[2] == "implement"


def test_convergence_loop_detected(monkeypatch):
    """Same inquiry with identical report -> blocked (loop)."""
    d, client = make_driver()
    calls = {"n": 0}

    def fake_judge(node_id, context, developer_report, extra_context, valid_targets, cancel):
        calls["n"] += 1
        return FakeReviewerResult("issue_pending", "ask_developer",
                                  message="请修复同一个问题")

    d._get_reviewer = lambda: type("R", (), {"judge": staticmethod(fake_judge)})()
    d._run_developer_node = lambda sid, nid, ctx: (None, "同样的汇报内容")

    result = d._run_reviewer_node("dev", "design", "ctx", None)
    assert result[0] is not None
    assert result[0].outcome == Outcome.BLOCKED
    assert "looping" in result[0].detail


def test_dialogue_rounds_exhausted(monkeypatch):
    """Persistent ask with changing reports but no advance -> exhausted."""
    d, client = make_driver({"max_dialogue_rounds": 3, "convergence_max_identical": 5})
    calls = {"n": 0}

    def fake_judge(node_id, context, developer_report, extra_context, valid_targets, cancel):
        calls["n"] += 1
        return FakeReviewerResult("issue_pending", "ask_developer",
                                  message=f"问题{calls['n']}")

    d._get_reviewer = lambda: type("R", (), {"judge": staticmethod(fake_judge)})()
    d._run_developer_node = lambda sid, nid, ctx: (None, f"汇报{calls['n']}")

    result = d._run_reviewer_node("dev", "design", "ctx", None)
    assert result[0] is not None
    assert result[0].outcome == Outcome.ERROR
    assert "exhausted" in result[0].detail


def test_session_rotation_on_capacity(monkeypatch):
    """Rotating the developer session refreshes the managed reference."""
    d, client = make_driver()
    d.sessions.ensure_developer("t")
    dev = d.sessions.developer
    old_sid = dev.session_id

    # stub lifecycle: always self-assess and decide to rotate
    from regime_driver.app.session_lifecycle import SessionLifecycle
    from regime_driver.core.policy import SelfAssessment, developer_policy

    class FakeLC(SessionLifecycle):
        def should_self_assess(self, state):
            return True
        def capacity_used(self, state):
            return 0.5
        def assess(self, state, usage=None):
            return SelfAssessment("ROTATE", milestone_reachable=True)
    d.session_lifecycle = FakeLC(d.settings, client, developer_policy_obj=developer_policy())

    rotated = d._check_session_capacity(dev, "design")
    assert rotated is True
    assert d.sessions.developer.session_id != old_sid
    # handover JSON was injected into the fresh session
    assert any('"kind":"brain_normal"' in s[1] for s in client.sent)