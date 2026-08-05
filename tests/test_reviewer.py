"""Tests for M-3: reviewer interaction, skill loading, task control."""

import json
import sys
from pathlib import Path

import pytest

from regime_driver.app.reviewer import Reviewer
from regime_driver.core.json_utils import extract_json
from regime_driver.core.state_machine import StateMachine
from regime_driver.infra.regime_loader import load_regime
from regime_driver.infra.skill_loader import SkillNotFoundError, load_skill
from regime_driver.infra.task_control import TaskControl

REGIME = Path(__file__).parent.parent / "src" / "regime_driver" / "data" / "regime.json"
SKILLS = Path(__file__).parent.parent / "workflow-regime" / "skills"


class FakeClient:
    """Minimal fake OpenCodeClient for reviewer tests."""

    def __init__(self, reply: str):
        self.reply = reply
        self.calls = []

    def ask_and_get_text(self, session_id, prompt, agent, model=None):
        self.calls.append((session_id, agent))
        return self.reply


def make_sm():
    return StateMachine.from_dict(REGIME.read_text(encoding="utf-8"))


def good_verdict(node="design", **overrides):
    v = {
        "node": node,
        "verdict": "advance",
        "action": "advance",
        "next_state": "implement",
        "confidence": 0.8,
        "reason": "ok",
    }
    v.update(overrides)
    return v


# --- reviewer parse ---------------------------------------------------------

def test_extract_json_fenced():
    text = '```json\n{"a":1}\n```'
    assert extract_json(text) == {"a": 1}


def test_extract_json_inline():
    text = 'prefix {"a":1} suffix'
    assert extract_json(text) == {"a": 1}


def test_extract_json_none():
    assert extract_json("no json here") is None


def test_reviewer_judge_ok():
    sm = make_sm()
    client = FakeClient(json.dumps(good_verdict()))
    reviewer = Reviewer(client, "s1", "reviewer", sm, skills_dir=str(SKILLS))
    result = reviewer.judge("design", "ctx")
    assert result.ok
    assert result.verdict.action == "advance"


def test_reviewer_judge_node_mismatch():
    sm = make_sm()
    client = FakeClient(json.dumps(good_verdict(node="wrong")))
    reviewer = Reviewer(client, "s1", "reviewer", sm, skills_dir=str(SKILLS))
    result = reviewer.judge("design", "ctx")
    assert not result.ok
    assert "node mismatch" in result.error


def test_reviewer_judge_bad_next_state():
    sm = make_sm()
    client = FakeClient(json.dumps(good_verdict(next_state="nope")))
    reviewer = Reviewer(client, "s1", "reviewer", sm, skills_dir=str(SKILLS))
    result = reviewer.judge("design", "ctx")
    assert not result.ok
    assert "next_state" in result.gate.reason


def test_reviewer_judge_no_json():
    sm = make_sm()
    client = FakeClient("no json")
    reviewer = Reviewer(client, "s1", "reviewer", sm)
    result = reviewer.judge("design", "ctx")
    assert not result.ok
    assert "no JSON" in result.error


def test_reviewer_injects_skill():
    sm = make_sm()
    client = FakeClient(json.dumps(good_verdict()))
    reviewer = Reviewer(client, "s1", "reviewer", sm, skills_dir=str(SKILLS))
    result = reviewer.judge("design", "ctx")  # design has skill=design-philosophy
    assert result.ok


# --- skill loader -----------------------------------------------------------

def test_load_skill_body():
    body = load_skill("design-philosophy", SKILLS)
    assert "设计哲学" in body
    assert "---" not in body.splitlines()[0]  # frontmatter stripped


def test_load_skill_not_found():
    with pytest.raises(SkillNotFoundError):
        load_skill("nope", SKILLS)


def test_load_skill_path_traversal_rejected():
    with pytest.raises(SkillNotFoundError):
        load_skill("../secret", SKILLS)
    with pytest.raises(SkillNotFoundError):
        load_skill("a/b", SKILLS)


# --- task control -----------------------------------------------------------

def test_task_control_read_write(tmp_path):
    tc = TaskControl(tmp_path)
    tc.init("next_steps")
    tc.append("next_steps", "do the thing")
    content = tc.read("next_steps")
    assert "do the thing" in content
    assert "# NEXT_STEPS.md" in content


def test_task_control_unknown_doc(tmp_path):
    tc = TaskControl(tmp_path)
    with pytest.raises(ValueError):
        tc.read("bogus")


def test_task_control_append_preserves(tmp_path):
    tc = TaskControl(tmp_path)
    tc.init("worklog")
    tc.append("worklog", "first")
    tc.append("worklog", "second")
    content = tc.read("worklog")
    assert "first" in content
    assert "second" in content


# --- successor-gated advance ------------------------------------------------

def test_advance_target_is_used():
    """Advance must return the reviewer's chosen target, not the static next."""
    sm = make_sm()
    client = FakeClient(json.dumps(good_verdict()))
    reviewer = Reviewer(client, "s1", "reviewer", sm, skills_dir=str(SKILLS))
    result = reviewer.judge("design", "ctx")
    assert result.ok
    assert result.verdict.next_state == "implement"


def test_successors_restricts_advance():
    """The reviewer may only advance to a successor of the current node."""
    sm = make_sm()
    assert sm.successors("design") == ["implement"]
    assert sm.successors("test") == ["wrap"]
    # backward advance must be rejected
    client = FakeClient(json.dumps(good_verdict(next_state="read_code")))
    reviewer = Reviewer(client, "s1", "reviewer", sm, skills_dir=str(SKILLS))
    result = reviewer.judge("design", "ctx")
    assert not result.ok
    assert "not in state machine" in result.gate.reason