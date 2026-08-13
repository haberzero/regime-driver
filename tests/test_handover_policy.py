"""Tests for the context-budget handover policy (WORK_PLAN13)."""

from __future__ import annotations

import pytest

from regime_driver.app.handover_policy import (
    ContextHandoverPolicy,
    build_handover_document,
    build_handover_opening,
)


class _Msg:
    def __init__(self, role, text):
        self.role = role
        self.text = text


def test_policy_from_json_defaults():
    p = ContextHandoverPolicy.from_json('{"soft_fraction": 0.5, "hard_fraction": 0.7}')
    assert p is not None
    assert p.enabled and p.soft_fraction == 0.5 and p.hard_fraction == 0.7
    assert p.min_continue_nodes == 2 and p.handover_keep_messages == 30


def test_policy_from_json_none_disables():
    assert ContextHandoverPolicy.from_json(None) is None
    assert ContextHandoverPolicy.from_json("") is None


def test_policy_from_json_invalid_fractions_rejected():
    with pytest.raises(ValueError):
        ContextHandoverPolicy.from_json('{"soft_fraction": 0.8, "hard_fraction": 0.3}')


def test_policy_from_json_invalid_json_rejected():
    with pytest.raises(ValueError):
        ContextHandoverPolicy.from_json("not json")


def test_handover_document_contains_state():
    msgs = [_Msg("user", "任务开始"), _Msg("assistant", "已完成 implement，63 passed")]
    doc = build_handover_document(
        role="developer", node_id="test", node_desc="测试与验证",
        task_context="重构库存子系统", messages=msgs, last_report="63 passed",
        keep=30, report_max_chars=1200)
    assert "会话交接文档" in doc
    assert "重构库存子系统" in doc
    assert "test" in doc
    assert "63 passed" in doc
    assert "已完成 implement" in doc


def test_handover_document_truncates_context_and_messages():
    msgs = [_Msg("assistant", "x" * 1000)]
    doc = build_handover_document(
        role="reviewer", node_id="a", node_desc="", task_context="t" * 1000,
        messages=msgs, last_report="r" * 5000, keep=1, report_max_chars=200)
    assert "…" in doc  # truncation marker present
    assert len([l for l in doc.splitlines() if l.startswith("  - [")]) == 1  # keep=1


def test_handover_opening_instructs_continuation():
    opening = build_handover_opening(
        role="developer", node_id="implement", node_desc="实现",
        task_context="任务X", document="# 会话交接文档", usage=0.62)
    assert "上下文交接" in opening
    assert "62%" in opening
    assert "implement" in opening
    assert "保持既有工作区产物与对外契约不变" in opening
