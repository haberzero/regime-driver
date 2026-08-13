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


def test_extract_json_prose_around_object():
    # the reviewer occasionally wraps the verdict in analysis prose
    text = ("方案需要进一步分析：因为并发边界未定。"
            '{"node":"design","verdict":"issue_pending","action":"ask_developer",'
            '"message_to_developer":"补齐设计","next_state":null,"confidence":0.8,'
            '"reason":"ok"}以上是判定。')
    assert extract_json(text)["node"] == "design"


def test_extract_json_brace_inside_string():
    text = '{"a": "{ not a real brace }", "b": 1} trailing'
    assert extract_json(text) == {"a": "{ not a real brace }", "b": 1}


def test_extract_json_skips_truncated_trailing():
    # token-limit cut at the END: complete object first, truncated object after
    text = '{"node":"test","verdict":"advance","action":"advance","next_state":"wrap",' + \
           '"confidence":0.9,"reason":"ok"}{"node": "design", "verdict": "advance", "confiden'
    obj = extract_json(text)
    assert obj is not None and obj["node"] == "test"


def test_extract_json_truncated_only_returns_none():
    assert extract_json('{"node": "design", "verdict": "advance"') is None


def test_extract_json_multiple_objects_takes_first_valid():
    text = '{"a":1} then {"b":2}'
    assert extract_json(text) == {"a": 1}


def test_extract_json_stray_closing_brace_in_prose():
    text = "答案：} 然后 {'a': 1}".replace("'", '"') + " 完成"
    assert extract_json(text) == {"a": 1}


def test_reviewer_parse_ok():
    sm = make_sm()
    reviewer = Reviewer(None, "s1", "reviewer", sm, skills_dir=str(SKILLS))
    result = reviewer.parse_reply(json.dumps(good_verdict()), "design")
    assert result.ok
    assert result.verdict.action == "advance"


def test_reviewer_parse_node_mismatch():
    sm = make_sm()
    reviewer = Reviewer(None, "s1", "reviewer", sm, skills_dir=str(SKILLS))
    result = reviewer.parse_reply(json.dumps(good_verdict(node="wrong")), "design")
    assert not result.ok
    assert "node mismatch" in result.error


def test_reviewer_parse_bad_next_state():
    sm = make_sm()
    reviewer = Reviewer(None, "s1", "reviewer", sm, skills_dir=str(SKILLS))
    result = reviewer.parse_reply(json.dumps(good_verdict(next_state="nope")), "design")
    assert not result.ok
    assert "next_state" in result.gate.reason


def test_reviewer_parse_no_json():
    sm = make_sm()
    reviewer = Reviewer(None, "s1", "reviewer", sm)
    result = reviewer.parse_reply("no json", "design")
    assert not result.ok
    assert "no JSON" in result.error


def test_reviewer_prompt_injects_skill():
    sm = make_sm()
    reviewer = Reviewer(None, "s1", "reviewer", sm, skills_dir=str(SKILLS))
    prompt = reviewer.prompt_for("design", "ctx")  # design has skill=design-philosophy
    assert "设计哲学" in prompt


# --- WORK_PLAN13 semantic gate (structured issues) --------------------------

def test_advance_with_blocking_issue_rejected():
    """A reviewer that documents a blocking finding must NOT advance: the gate
    rejects the contradiction (this is the kv_failover-advance class of bug)."""
    sm = make_sm()
    reviewer = Reviewer(None, "s1", "reviewer", sm, skills_dir=str(SKILLS))
    v = good_verdict()
    v["issues"] = [{"severity": "blocking", "summary": "failover can lose committed writes"}]
    result = reviewer.parse_reply(json.dumps(v), "design")
    assert not result.ok
    assert "blocking" in result.gate.reason


def test_advance_with_only_warnings_allowed():
    sm = make_sm()
    reviewer = Reviewer(None, "s1", "reviewer", sm, skills_dir=str(SKILLS))
    v = good_verdict()
    v["issues"] = [{"severity": "warning", "summary": "narrow window, documented tech debt"}]
    result = reviewer.parse_reply(json.dumps(v), "design")
    assert result.ok


def test_ask_developer_with_blocking_issue_allowed():
    sm = make_sm()
    reviewer = Reviewer(None, "s1", "reviewer", sm, skills_dir=str(SKILLS))
    v = good_verdict()
    v.update({"verdict": "issue_pending", "action": "ask_developer",
              "next_state": None,
              "message_to_developer": "请修复 ref 命名空间冲突",
              "issues": [{"severity": "blocking", "summary": "ref namespace collision"}]})
    result = reviewer.parse_reply(json.dumps(v), "design")
    assert result.ok


def test_issues_parsed_into_verdict():
    sm = make_sm()
    reviewer = Reviewer(None, "s1", "reviewer", sm, skills_dir=str(SKILLS))
    v = good_verdict()
    v["issues"] = [{"severity": "warning", "summary": "w1", "detail": "d1"}]
    result = reviewer.parse_reply(json.dumps(v), "design")
    assert result.ok
    assert result.verdict.issues[0].severity == "warning"
    assert result.verdict.issues[0].detail == "d1"


def test_verdict_without_issues_defaults_empty():
    sm = make_sm()
    reviewer = Reviewer(None, "s1", "reviewer", sm, skills_dir=str(SKILLS))
    result = reviewer.parse_reply(json.dumps(good_verdict()), "design")
    assert result.ok
    assert result.verdict.issues == []


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
    reviewer = Reviewer(None, "s1", "reviewer", sm, skills_dir=str(SKILLS))
    result = reviewer.parse_reply(json.dumps(good_verdict()), "design")
    assert result.ok
    assert result.verdict.next_state == "implement"


def test_successors_restricts_advance():
    """The reviewer may only advance to a successor of the current node."""
    sm = make_sm()
    assert sm.successors("design") == ["implement"]
    assert sm.successors("test") == ["wrap"]
    # backward advance must be rejected
    reviewer = Reviewer(None, "s1", "reviewer", sm, skills_dir=str(SKILLS))
    result = reviewer.parse_reply(json.dumps(good_verdict(next_state="read_code")), "design")
    assert not result.ok
    assert "not in state machine" in result.gate.reason