"""Tests for deterministic tool/route/gate nodes + workspace + transition fixes."""

import pytest

from regime_driver.app.driver import RegimeDriver
from regime_driver.core.branching import ConditionError, evaluate, resolve_branch
from regime_driver.core.models import Node, NodeType, Outcome, Regime, RegimeMeta, FlowEntry, Flow
from regime_driver.core.policy import TransitionDecision, workspace_for
from regime_driver.core.state_machine import StateMachine
from regime_driver.core.tools import UnknownToolError, run_tool
from regime_driver.infra.settings import Settings


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


# ------------------------------------------------- driver tool/route/gate

def _sm_with_nodes(nodes):
    flow = Flow(nodes={n.id: n for n in nodes})
    regime = Regime(version="t", meta=RegimeMeta(), flows={"f": flow},
                    entry=FlowEntry(flow="f", start_node=nodes[0].id))
    return StateMachine(regime)


class _FakeClient:
    def __init__(self):
        self.created = 0
    def create_session(self, title):
        self.created += 1
        return f"ses_{self.created}"
    def send_message(self, sid, text, agent): pass
    def session_tokens(self, sid): return (0, 0)
    def session_status(self, sid): return "idle"
    def read_messages(self, sid): return []
    def abort_session(self, sid): pass
    def delete_session(self, sid): pass


def _driver_for_nodes(nodes, settings_overrides=None):
    sm = _sm_with_nodes(nodes)
    client = _FakeClient()
    s = Settings(monitor_enabled=False, **(settings_overrides or {}))
    d = RegimeDriver(s, sm, client)
    return d, client


def test_tool_node_runs_and_advances():
    tool = Node(id="t", desc="check", type=NodeType.TOOL, tool="have_report", next="end")
    end = Node(id="end", desc="done", type=NodeType.AGENT, next=None)
    d, client = _driver_for_nodes([tool, end])
    d._run_agent_node = lambda sid, role, nid, ctx: (None, "done")
    result = d.run("ctx")
    assert result.outcome == Outcome.COMPLETE
    assert d._env["ok"] is False  # no report yet when tool ran


def test_route_node_branches_to_match():
    produce = Node(id="p", desc="produce", type=NodeType.AGENT, next="r")
    route = Node(id="r", desc="route", type=NodeType.ROUTE,
                 branches=[{"when": "report contains 'good'", "goto": "ok_node"}],
                 next="bad_node")
    ok_node = Node(id="ok_node", desc="ok", type=NodeType.AGENT, next=None)
    bad_node = Node(id="bad_node", desc="bad", type=NodeType.AGENT, next=None)
    d, client = _driver_for_nodes([produce, route, ok_node, bad_node])
    executed = []
    def fake_agent(sid, role, nid, ctx):
        executed.append(nid)
        return (None, "good work done" if nid == "p" else f"{nid} report good")
    d._run_agent_node = fake_agent
    result = d.run("ctx")
    assert result.outcome == Outcome.COMPLETE
    assert executed == ["p", "ok_node"]  # routed to the branch, not the fallback


def test_route_node_falls_through_to_next():
    produce = Node(id="p", desc="produce", type=NodeType.AGENT, next="r")
    route = Node(id="r", desc="route", type=NodeType.ROUTE,
                 branches=[{"when": "report contains 'good'", "goto": "ok_node"}],
                 next="bad_node")
    ok_node = Node(id="ok_node", desc="ok", type=NodeType.AGENT, next=None)
    bad_node = Node(id="bad_node", desc="bad", type=NodeType.AGENT, next=None)
    d, client = _driver_for_nodes([produce, route, ok_node, bad_node])
    executed = []
    def fake_agent(sid, role, nid, ctx):
        executed.append(nid)
        return (None, "nothing changed")
    d._run_agent_node = fake_agent
    result = d.run("ctx")
    assert executed == ["p", "bad_node"]  # no branch matched -> next


def test_gate_blocked_when_no_branch_matches():
    produce = Node(id="p", desc="produce", type=NodeType.AGENT, next="g")
    gate = Node(id="g", desc="gate", type=NodeType.GATE,
                branches=[{"when": "report contains 'pass'", "goto": "end"}],
                next="end")
    end = Node(id="end", desc="done", type=NodeType.AGENT, next=None)
    d, client = _driver_for_nodes([produce, gate, end])
    d._run_agent_node = lambda sid, role, nid, ctx: (None, "nothing changed")
    result = d.run("ctx")
    assert result.outcome == Outcome.BLOCKED
    assert "not satisfied" in result.detail


def test_gate_passes_when_branch_matches():
    produce = Node(id="p", desc="produce", type=NodeType.AGENT, next="g")
    gate = Node(id="g", desc="gate", type=NodeType.GATE,
                branches=[{"when": "report contains 'pass'", "goto": "end"}],
                next="end")
    end = Node(id="end", desc="done", type=NodeType.AGENT, next=None)
    d, client = _driver_for_nodes([produce, gate, end])
    def fake_agent(sid, role, nid, ctx):
        return (None, "pass ok" if nid == "p" else "done")
    d._run_agent_node = fake_agent
    result = d.run("ctx")
    assert result.outcome == Outcome.COMPLETE


def test_workspace_hint_in_instruction():
    d, client = _driver_for_nodes([Node(id="a", desc="work", type=NodeType.AGENT, next=None)])
    instr = d._build_instruction("a", "ctx", "developer")
    assert "code" in instr


def test_anchor_transition_pins_session():
    from regime_driver.core.policy import RolePolicy
    from regime_driver.core.role import Role, RoleRegistry
    from regime_driver.app.session_manager import SessionRegistry

    roles = RoleRegistry()
    roles.register(Role(id="reviewer", agent="reviewer",
                        policy=RolePolicy(transition_mode=TransitionDecision.ANCHOR)))
    d, client = _driver_for_nodes([Node(id="a", desc="", role="reviewer",
                                        type=NodeType.AGENT, next=None)])
    d.roles = roles
    d.sessions = SessionRegistry(client, agent_by_role={"reviewer": "reviewer"})
    d.session_rotator.sessions = d.sessions
    d.sessions.ensure("reviewer", "t")
    old_sid = d.sessions.get("reviewer").session_id
    rotated = d._apply_transition("a", "dummy", {})
    assert rotated == set()
    assert d.sessions.get("reviewer").session_id == old_sid  # anchored, not rotated


def test_transition_rotate_returns_rotated_role_set():
    from regime_driver.core.policy import RolePolicy
    from regime_driver.core.role import Role, RoleRegistry
    from regime_driver.app.session_manager import SessionRegistry

    roles = RoleRegistry()
    roles.register(Role(id="reviewer", agent="reviewer",
                        policy=RolePolicy(transition_mode=TransitionDecision.ROTATE)))
    d, client = _driver_for_nodes([Node(id="a", desc="", role="reviewer",
                                        type=NodeType.AGENT, next=None)])
    d.roles = roles
    d.sessions = SessionRegistry(client, agent_by_role={"reviewer": "reviewer"})
    d.session_rotator.sessions = d.sessions
    d.sessions.ensure("reviewer", "t")
    rotated = d._apply_transition("a", "dummy", {})
    assert rotated == {"reviewer"}


# ---------------------------------------------------------- config validation

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