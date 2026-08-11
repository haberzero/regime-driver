"""Tests for the core domain layer (pure, no I/O)."""

import json
import sys
from pathlib import Path

import pytest

from regime_driver.core.contract import (
    ContractError,
    gate_reviewer_verdict,
    parse_reviewer_verdict,
)
from regime_driver.core.models import ReviewerVerdict
from regime_driver.core.segment import SegmentParser
from regime_driver.core.session import SessionState
from regime_driver.core.state_machine import StateMachine, StateMachineError
from regime_driver.infra.regime_loader import load_regime

REGIME = Path(__file__).parent.parent / "src" / "regime_driver" / "data" / "regime.json"


def make_verdict(**overrides) -> dict:
    base = {
        "node": "design",
        "verdict": "issue_resolved",
        "action": "advance",
        "next_state": "implement",
        "confidence": 0.8,
        "reason": "done",
    }
    base.update(overrides)
    return base


# --- deterministic gate -----------------------------------------------------

def test_valid_advance():
    v = parse_reviewer_verdict(make_verdict())
    res = gate_reviewer_verdict(v)
    assert res.ok, res.reason


def test_ask_developer_requires_message():
    v = parse_reviewer_verdict(make_verdict(action="ask_developer"))
    res = gate_reviewer_verdict(v)
    assert not res.ok
    assert "message_to_developer" in res.reason


def test_advance_requires_valid_next_state():
    v = parse_reviewer_verdict(make_verdict())
    res = gate_reviewer_verdict(v, valid_node_ids={"test"})
    assert not res.ok
    assert "next_state" in res.reason


def test_terminal_judge_advance_with_null_next_state_ok():
    # a judge on a terminal node (no successors) completes the flow with
    # next_state=null — regression for the "reviewer gate exhausted" bug on
    # final-review judge flows.
    v = parse_reviewer_verdict(make_verdict(next_state=None))
    res = gate_reviewer_verdict(v, valid_node_ids=set())
    assert res.ok, res.reason


def test_terminal_judge_advance_with_non_null_next_state_rejected():
    # terminal node has no valid targets; naming a concrete next_state is invalid
    v = parse_reviewer_verdict(make_verdict(next_state="implement"))
    res = gate_reviewer_verdict(v, valid_node_ids=set())
    assert not res.ok
    assert "terminal node" in res.reason


def test_bad_verdict_rejected():
    with pytest.raises(ContractError):
        parse_reviewer_verdict(make_verdict(verdict="slomo"))


def test_confidence_below_min():
    v = parse_reviewer_verdict(
        make_verdict(verdict="blocked", action="report_user", confidence=0.2)
    )
    res = gate_reviewer_verdict(v)
    assert not res.ok
    assert "confidence" in res.reason


def test_verdict_action_inconsistent():
    v = parse_reviewer_verdict(
        make_verdict(verdict="blocked", action="advance", next_state="x")
    )
    res = gate_reviewer_verdict(v)
    assert not res.ok


def test_confidence_out_of_bounds():
    # pydantic Field(le=1.0) rejects out-of-range at the model layer.
    with pytest.raises(ContractError):
        parse_reviewer_verdict(make_verdict(confidence=1.5))


# --- segment protocol -------------------------------------------------------

def test_segment_found():
    p = SegmentParser()
    text = "改动了 foo.py\n测试通过: 3 passed\n[WORK_DONE]"
    assert p.has_segment_end(text)
    assert "foo.py" in (p.extract_report(text) or "")


def test_segment_missing():
    p = SegmentParser()
    assert not p.has_segment_end("just talking")
    assert p.extract_report("no marker") is None


def test_marker_must_be_own_line():
    p = SegmentParser()
    assert not p.has_segment_end("not a marker [WORK_DONE] inline")


def test_marker_custom():
    p = SegmentParser(marker="[FINISHED]")
    assert p.has_segment_end("x\n[FINISHED]")
    assert not p.has_segment_end("x\n[WORK_DONE]")


def test_parse_report_structured():
    p = SegmentParser()
    report = p.parse(
        "文件: calc.py, test_calc.py\n"
        "测试命令: python -m pytest\n"
        "测试结果: 3 passed\n"
        "技术债: 无\n"
        "待决点: 无\n"
        "[WORK_DONE]"
    )
    assert report is not None
    assert report.files_changed == ["calc.py", "test_calc.py"]
    assert report.test_command == "python -m pytest"
    assert report.test_result == "3 passed"


# --- state machine -----------------------------------------------------------

def test_state_machine_loads_from_real_regime():
    sm = load_regime(REGIME)
    assert sm.flow_name == "code_workflow"
    assert sm.start == "understand"
    path = sm.flow_path()
    assert path[0] == "understand"
    assert path[-1] == "wrap"


def test_state_machine_cycle_detected():
    raw = json.dumps(
        {
            "version": "0.1",
            "flows": {
                "f": {
                    "nodes": {
                        "a": {"id": "a", "desc": "", "role": "developer", "next": "b"},
                        "b": {"id": "b", "desc": "", "role": "developer", "next": "a"},
                    }
                }
            },
            "entry": {"flow": "f", "start_node": "a"},
        }
    )
    sm = StateMachine.from_dict(raw)
    with pytest.raises(StateMachineError):
        sm.flow_path()


def test_state_machine_bad_next_rejected():
    raw = json.dumps(
        {
            "version": "0.1",
            "flows": {
                "f": {
                    "nodes": {
                        "a": {"id": "a", "desc": "", "role": "developer", "next": "nope"},
                    }
                }
            },
            "entry": {"flow": "f", "start_node": "a"},
        }
    )
    with pytest.raises(StateMachineError):
        StateMachine.from_dict(raw)


# --- session ----------------------------------------------------------------

def test_session_turn_check():
    s = SessionState("developer", "s1")
    assert not s.turn_check_due(5)
    s.advance_round()
    s.advance_round()
    s.advance_round()
    s.advance_round()
    s.advance_round()
    assert s.round == 5
    assert s.turn_check_due(5)


def test_session_turn_check_disabled():
    s = SessionState("developer", "s1")
    s.advance_round()
    assert not s.turn_check_due(0)