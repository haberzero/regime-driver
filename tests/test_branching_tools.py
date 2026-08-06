"""Tests for deterministic tool/route/gate nodes + workspace + transition fixes."""

import pytest

from regime_driver.core.branching import ConditionError, evaluate, resolve_branch
from regime_driver.core.models import Node, NodeType, Regime, RegimeMeta, FlowEntry, Flow
from regime_driver.core.policy import workspace_for
from regime_driver.core.state_machine import StateMachine
from regime_driver.core.tools import UnknownToolError, run_tool


# ---------------------------------------------------------------- branching

def test_evaluate_basic_operators():
    env = {"report": "fixed bug in parser", "context": "fix parser", "ok": True}
    assert evaluate("report contains 'bug'", env) is True
    assert evaluate("report contains 'nope'", env) is False
    assert evaluate("'bug' in report", env) is True
    assert evaluate("context == 'fix parser'", env) is True
    assert evaluate("context != 'nope'", env) is True
    assert evaluate("ok", env) is True


def test_evaluate_boolean_and_not():
    env = {"report": "fixed", "context": "go", "ok": True}
    assert evaluate("report contains 'fix' and ok", env) is True
    assert evaluate("report contains 'fix' and not ok", env) is False
    assert evaluate("report contains 'fix' or ok", env) is True
    assert evaluate("(ok or report contains 'z') and context != ''", env) is True


def test_evaluate_unknown_variable_raises():
    with pytest.raises(ConditionError):
        evaluate("bogus contains 'x'", {"report": "a"})


def test_evaluate_malformed_raises():
    with pytest.raises(ConditionError):
        evaluate("report contains", {"report": "a"})
    with pytest.raises(ConditionError):
        evaluate("report contains 'a' junk", {"report": "a"})


def test_evaluate_numeric_comparison_int_float():
    assert evaluate("x == 3", {"x": 3}) is True
    assert evaluate("x == 3", {"x": 3.0}) is True
    assert evaluate("x == 3", {"x": 4}) is False
    assert evaluate("x != 3", {"x": 4}) is True


def test_evaluate_string_false_is_falsy():
    assert evaluate("ok", {"ok": "false"}) is False
    assert evaluate("ok", {"ok": "true"}) is True
    assert evaluate("ok", {"ok": "yes"}) is True  # non-empty non-boolean string is truthy
    assert evaluate("ok", {"ok": ""}) is False


def test_resolve_branch_first_match_wins():
    node = Node(id="r", desc="", type=NodeType.ROUTE,
                branches=[{"when": "report contains 'X'", "goto": "a"},
                          {"when": "report contains 'Y'", "goto": "b"}])
    assert resolve_branch(node, {"report": "X"}) == "a"
    assert resolve_branch(node, {"report": "Y and X"}) == "a"  # order matters
    assert resolve_branch(node, {"report": "Y"}) == "b"
    assert resolve_branch(node, {"report": "Z"}) is None


# ---------------------------------------------------------------- tools

def test_tools_noop_and_have_report():
    assert run_tool(Node(id="t", desc="", type=NodeType.TOOL, tool="noop"), "ctx", "rep").ok
    assert run_tool(Node(id="t", desc="", type=NodeType.TOOL, tool="have_report"), "ctx", "rep").ok
    assert run_tool(Node(id="t", desc="", type=NodeType.TOOL, tool="have_report"), "ctx", "").ok is False


def test_tools_mentions():
    n = Node(id="t", desc="", type=NodeType.TOOL, tool="report_mentions", tool_args={"words": ["bug", "fixed"]})
    assert run_tool(n, "ctx", "bug is fixed now").ok
    assert run_tool(Node(id="t", desc="", type=NodeType.TOOL, tool="report_mentions",
                         tool_args={"word": "bug"}), "ctx", "everything ok").ok is False
    c = Node(id="t", desc="", type=NodeType.TOOL, tool="context_mentions", tool_args={"word": "parser"})
    assert run_tool(c, "fix the parser", "rep").ok is True


def test_unknown_tool_raises():
    with pytest.raises(UnknownToolError):
        run_tool(Node(id="t", desc="", type=NodeType.TOOL, tool="nope"), "ctx", "rep")


def test_mentions_tool_without_words_fails():
    r = run_tool(Node(id="t", desc="", type=NodeType.TOOL, tool="report_mentions"), "ctx", "anything")
    assert r.ok is False
    c = run_tool(Node(id="t", desc="", type=NodeType.TOOL, tool="context_mentions"), "ctx", "rep")
    assert c.ok is False


# ---------------------------------------------------------------- workspace

def test_workspace_for_conventions():
    assert workspace_for("developer")["work_dir"] == "code"
    assert workspace_for("reviewer")["writable"] == ["handoff"]
    assert workspace_for("unknown")["work_dir"] == "."


# ---------------------------------------------------------- config validation

def _sm_with_nodes(nodes):
    flow = Flow(nodes={n.id: n for n in nodes})
    regime = Regime(version="t", meta=RegimeMeta(), flows={"f": flow},
                    entry=FlowEntry(flow="f", start_node=nodes[0].id))
    return StateMachine(regime)


def test_tool_node_without_tool_name_fails_validation():
    bad = Node(id="t", desc="", type=NodeType.TOOL, tool=None, next=None)
    with pytest.raises(Exception) as exc:
        _sm_with_nodes([bad])
    assert "must declare a tool name" in str(exc.value)


def test_route_without_branches_fails_validation():
    bad = Node(id="r", desc="", type=NodeType.ROUTE, next=None)
    with pytest.raises(Exception) as exc:
        _sm_with_nodes([bad])
    assert "must declare at least one branch" in str(exc.value)


def test_gate_without_branches_fails_validation():
    bad = Node(id="g", desc="", type=NodeType.GATE, next=None)
    with pytest.raises(Exception) as exc:
        _sm_with_nodes([bad])
    assert "must declare at least one branch" in str(exc.value)


def test_valid_tool_with_branch_passes_validation():
    node = Node(id="t", desc="", type=NodeType.TOOL, tool="have_report",
                next="end", branches=[{"when": "ok", "goto": "end"}])
    end = Node(id="end", desc="", type=NodeType.AGENT, next=None)
    sm = _sm_with_nodes([node, end])
    assert sm.flow_name == "f"