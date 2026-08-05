"""Tests for the meta-analyzer (independent stall review)."""

import json

from regime_driver.app.meta_analyzer import MetaAnalyzer
from regime_driver.core.json_utils import extract_json
from regime_driver.infra.opencode import Message
from regime_driver.infra.settings import Settings


class FakeClient:
    def __init__(self, reply):
        self.reply = reply
        self.calls = []

    def ask_and_get_text(self, session_id, prompt, agent, model=None):
        self.calls.append((session_id, prompt, agent))
        return self.reply

    def create_session(self, title):
        return "meta-test"


def make_analyzer(reply):
    settings = Settings(meta_analyze_enabled=True, meta_model="deepseek-api/deepseek-v4-flash")
    return MetaAnalyzer(settings, FakeClient(reply))


def test_extract_json_fenced():
    assert extract_json('```json\n{"a":1}\n```') == {"a": 1}
    assert extract_json("no json") is None


def test_meta_normal():
    a = make_analyzer(json.dumps({"verdict": "normal", "confidence": 0.9,
                                  "recommended_action": "none", "reason": "ok", "evidence": "e"}))
    r = a.analyze("s1", "goal", "deadline", [], [])
    assert r.ok
    assert r.verdict == "normal"
    assert r.action == "none"


def test_meta_stalled_abort():
    a = make_analyzer(json.dumps({"verdict": "stalled", "confidence": 0.8,
                                  "recommended_action": "abort", "reason": "stuck", "evidence": "e"}))
    r = a.analyze("s1", "goal", "deadline", [], [])
    assert r.ok
    assert r.verdict == "stalled"
    assert r.action == "abort"


def test_meta_gate_rejects_bad_verdict():
    a = make_analyzer(json.dumps({"verdict": "bogus", "confidence": 0.9,
                                  "recommended_action": "abort", "reason": "x", "evidence": "e"}))
    r = a.analyze("s1", "goal", "deadline", [], [])
    assert not r.ok
    assert "not allowed" in r.error


def test_meta_gate_rejects_inconsistent():
    a = make_analyzer(json.dumps({"verdict": "normal", "confidence": 0.9,
                                  "recommended_action": "abort", "reason": "x", "evidence": "e"}))
    r = a.analyze("s1", "goal", "deadline", [], [])
    assert not r.ok
    assert "inconsistent" in r.error


def test_meta_gate_rejects_low_confidence():
    a = make_analyzer(json.dumps({"verdict": "blocked", "confidence": 0.1,
                                  "recommended_action": "human", "reason": "x", "evidence": "e"}))
    r = a.analyze("s1", "goal", "deadline", [], [])
    assert not r.ok
    assert "confidence" in r.error


def test_meta_no_json():
    a = make_analyzer("no json here")
    r = a.analyze("s1", "goal", "deadline", [], [])
    assert not r.ok
    assert "no JSON" in r.error


def test_meta_builds_context_with_timestamps():
    a = make_analyzer('{"verdict":"normal"}')
    msgs = [Message(id="m1", role="assistant", text="doing work", ts="2026-01-01T00:00:00")]
    a.analyze("s1", "goal", "deadline", msgs, [])
    # the client captured the prompt; ensure it contains the timestamped message
    prompt = a.client.calls[0][1]
    assert "2026-01-01T00:00:00" in prompt
    assert "doing work" in prompt