"""Tests for v4 orchestration: multi-round interrogation, convergence, rotation."""

from regime_driver.app.driver import RegimeDriver
from regime_driver.app.session_lifecycle import SessionLifecycle
from regime_driver.core.models import Outcome
from regime_driver.core.policy import SelfAssessment
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


def _stub_reviewer(d, fake_judge):
    """Replace _get_reviewer with a stub returning a judge that calls fake_judge."""
    class R:
        def judge(self, node_id, context, developer_report, extra_context,
                  valid_targets, cancel):
            return fake_judge(node_id, context, developer_report, extra_context,
                              valid_targets, cancel)
    d._get_reviewer = lambda role_id: R()


def test_multiround_interrogation_converges_on_advance():
    d, client = make_driver()
    d.sessions.ensure("developer", "t")
    calls = {"n": 0}

    def fake_judge(node_id, context, report, extra, targets, cancel):
        calls["n"] += 1
        if calls["n"] <= 2:
            return FakeReviewerResult("issue_pending", "ask_developer",
                                      message=f"请修复第{calls['n']}轮问题")
        return FakeReviewerResult("advance", "advance", next_state="implement")

    _stub_reviewer(d, fake_judge)
    d._run_agent_node = lambda sid, role, nid, ctx: (None, f"汇报第{calls['n']}轮")

    result = d._run_reviewer_node("dev", "reviewer", "developer", "design", "ctx", None)
    assert result[0] is None
    assert result[2] == "implement"


def test_convergence_loop_detected():
    d, client = make_driver()
    d.sessions.ensure("developer", "t")
    calls = {"n": 0}

    def fake_judge(node_id, context, report, extra, targets, cancel):
        calls["n"] += 1
        return FakeReviewerResult("issue_pending", "ask_developer",
                                  message="请修复同一个问题")

    _stub_reviewer(d, fake_judge)
    d._run_agent_node = lambda sid, role, nid, ctx: (None, "同样的汇报内容")

    result = d._run_reviewer_node("dev", "reviewer", "developer", "design", "ctx", None)
    assert result[0] is not None
    assert result[0].outcome == Outcome.BLOCKED
    assert "looping" in result[0].detail


def test_dialogue_rounds_exhausted():
    d, client = make_driver({"max_dialogue_rounds": 3, "convergence_max_identical": 5})
    d.sessions.ensure("developer", "t")
    calls = {"n": 0}

    def fake_judge(node_id, context, report, extra, targets, cancel):
        calls["n"] += 1
        return FakeReviewerResult("issue_pending", "ask_developer",
                                  message=f"问题{calls['n']}")

    _stub_reviewer(d, fake_judge)
    d._run_agent_node = lambda sid, role, nid, ctx: (None, f"汇报{calls['n']}")

    result = d._run_reviewer_node("dev", "reviewer", "developer", "design", "ctx", None)
    assert result[0] is not None
    assert result[0].outcome == Outcome.ERROR
    assert "exhausted" in result[0].detail


def test_session_rotation_on_capacity():
    d, client = make_driver()
    d.sessions.ensure("developer", "t")
    dev = d.sessions.get("developer")
    old_sid = dev.session_id

    class FakeLC(SessionLifecycle):
        def should_self_assess(self, state):
            return True
        def capacity_used(self, state):
            return 0.5
        def assess(self, state, usage=None):
            return SelfAssessment("ROTATE", milestone_reachable=True)
    d.session_lifecycle = FakeLC(d.settings, client, d.roles)

    rotated = d._check_session_capacity(dev, "design")
    assert rotated is True
    assert d.sessions.get("developer").session_id != old_sid
    assert any('"kind":"brain_normal"' in s[1] for s in client.sent)