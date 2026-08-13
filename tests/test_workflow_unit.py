"""Tests for the WorkflowUnit (governed state machine driving a flow)."""

import json
import re
import time

from regime_driver.app.workflow_unit import WorkflowUnit
from regime_driver.core.models import Outcome
from regime_driver.core.statechart import SignalKind
from regime_driver.infra.ledger import Ledger
from regime_driver.infra.regime_loader import load_regime
from regime_driver.infra.settings import Settings

# successor map for the real code_workflow: judge node -> valid advance target
SUCC = {"design": "implement", "test": "wrap"}


class Message:
    def __init__(self, role, text="", error=None, completed=None, reply=None,
                 finish="stop"):
        self.role = role
        self.text = text
        self.error = error
        self.completed = completed
        self.reply = reply if reply is not None else text
        # default 'stop' = a normally-finished turn in tests; abort scenarios
        # pass error=... or finish=None explicitly.
        self.finish = finish


class FakeClient:
    def __init__(self):
        self.created = 0
        self.msgs = {}
        self.status = {}
        self.tokens = {}
        self.sent = []

    def create_session(self, title):
        self.created += 1
        return f"ses_{self.created}"

    def send_message(self, sid, text, agent):
        self.sent.append((sid, text, agent))
        if agent == "reviewer":
            m = re.search(r"当前节点：(\w+)", text)
            node = m.group(1) if m else "design"
            verdict = {"node": node, "verdict": "advance", "action": "advance",
                       "next_state": SUCC.get(node, "wrap"), "confidence": 0.9, "reason": "ok"}
            self.msgs[sid] = [Message("assistant", json.dumps(verdict))]
        else:  # developer
            self.msgs[sid] = [Message("assistant", "done work\n[WORK_DONE]")]

    def read_messages(self, sid):
        return self.msgs.get(sid, [])

    def session_status(self, sid):
        return "idle"

    def session_tokens(self, sid):
        return (0, 0)

    def abort_session(self, sid):
        pass


def _make(overrides=None):
    s = Settings(monitor_enabled=False, **(overrides or {}))
    sm = load_regime()
    client = FakeClient()
    unit = WorkflowUnit(s, sm, client, poll_sec=0.05)
    return unit, client


def _wait_result(unit, timeout=5.0):
    deadline = time.time() + timeout
    while unit.result() is None and time.time() < deadline:
        time.sleep(0.02)
    return unit.result()


def test_full_flow_completes():
    unit, client = _make()
    unit.start()
    unit.submit("实现一个反转函数")
    outcome, end, detail = _wait_result(unit)
    unit.stop()
    assert outcome == Outcome.COMPLETE
    assert end == "wrap"


def test_stop_signal_aborts():
    unit, client = _make()
    unit.start()
    unit.submit("实现一个反转函数")
    time.sleep(0.1)
    unit.deliver(_sig(unit, "watchdog", SignalKind.STOP, {"reason": "test stop"}))
    outcome, end, detail = _wait_result(unit)
    unit.stop()
    assert outcome == Outcome.BLOCKED
    assert "monitor" in detail


def test_watchdog_reports_emitted():
    from regime_driver.core.statechart import Bus, SignalKind, StatechartUnit

    bus = Bus()
    got = []
    cons = StatechartUnit("watchdog")
    cons.register(SignalKind.REPORT, lambda s: got.append(s.payload))
    bus.register(cons)
    s = Settings(monitor_enabled=False)
    sm = load_regime()
    client = FakeClient()
    unit = WorkflowUnit(s, sm, client, poll_sec=0.05, bus=bus)
    unit.start()
    unit.submit("任务")
    deadline = time.time() + 3
    while not got and time.time() < deadline:
        time.sleep(0.02)
    unit.stop()
    assert got, "workflow never reported its session state to the watchdog"
    assert got[0].get("session_id")  # report carries the alive session id


# --- interrogation / rework / convergence ---------------------------------

class ScriptedClient(FakeClient):
    """Reviewer returns a scripted sequence for ONE judge node; others default-advance."""

    def __init__(self, reviewer_script, script_node="design"):
        super().__init__()
        self.reviewer_script = list(reviewer_script)
        self.script_node = script_node
        self.reviewer_calls = 0
        self.scripted_calls = 0

    def send_message(self, sid, text, agent):
        if agent == "reviewer":
            m = re.search(r"当前节点：(\w+)", text)
            node = m.group(1) if m else "design"
            if node == self.script_node and self.reviewer_calls < len(self.reviewer_script):
                v = self.reviewer_script[self.reviewer_calls]
                self.scripted_calls += 1
            else:
                # default: advance to the node's successor
                v = {"node": node, "verdict": "advance", "action": "advance",
                     "next_state": SUCC.get(node, "wrap"), "confidence": 0.9, "reason": "ok"}
            self.reviewer_calls += 1
            self.msgs[sid] = [Message("assistant", json.dumps(v))]
        else:
            self.msgs[sid] = [Message("assistant", "rework done\n[WORK_DONE]")]


def _ask_verdict(node="design", msg="请修复"):
    return {"node": node, "verdict": "issue_pending", "action": "ask_developer",
            "message_to_developer": msg, "confidence": 0.9, "reason": msg}


def test_multiround_interrogation_converges_on_advance():
    script = [_ask_verdict("design", "fix A"),
              _ask_verdict("design", "fix B"),
              {"node": "design", "verdict": "advance", "action": "advance",
               "next_state": "implement", "confidence": 0.9, "reason": "ok"}]
    s = Settings(monitor_enabled=False, max_dialogue_rounds=5)
    sm = load_regime()
    client = ScriptedClient(script)
    unit = WorkflowUnit(s, sm, client, poll_sec=0.05)
    unit.start()
    unit.submit("任务")
    outcome, end, detail = _wait_result(unit)
    unit.stop()
    assert outcome == Outcome.COMPLETE
    assert client.scripted_calls == 3  # two reworks then advance on the design node


def test_convergence_loop_detected():
    script = [_ask_verdict("design", "same problem") for _ in range(6)]
    s = Settings(monitor_enabled=False, convergence_max_identical=2)
    sm = load_regime()
    client = ScriptedClient(script)
    unit = WorkflowUnit(s, sm, client, poll_sec=0.05)
    unit.start()
    unit.submit("任务")
    outcome, end, detail = _wait_result(unit)
    unit.stop()
    assert outcome == Outcome.BLOCKED
    assert "looping" in detail


def test_dialogue_rounds_exhausted():
    script = [_ask_verdict("design", f"fix {i}") for i in range(10)]
    s = Settings(monitor_enabled=False, max_dialogue_rounds=3)
    sm = load_regime()
    client = ScriptedClient(script)
    unit = WorkflowUnit(s, sm, client, poll_sec=0.05)
    unit.start()
    unit.submit("任务")
    outcome, end, detail = _wait_result(unit)
    unit.stop()
    assert outcome == Outcome.ERROR
    assert "dialogue rounds exhausted" in detail


def test_native_completion_without_marker():
    """A developer turn that completes (info.time.completed) is node-done with no [WORK_DONE]."""
    class NativeClient(FakeClient):
        def send_message(self, sid, text, agent):
            if agent == "reviewer":
                super().send_message(sid, text, agent)
            else:
                # assistant turn finished, no [WORK_DONE] marker
                self.msgs[sid] = [Message("assistant", "完成了 add 函数",
                                          completed="1786008000000", reply="完成了 add 函数")]
    s = Settings(monitor_enabled=False, poll_sec=0.1)
    sm = load_regime()
    client = NativeClient()
    unit = WorkflowUnit(s, sm, client, poll_sec=0.1)
    unit.start()
    unit.submit("任务")
    outcome, end, detail = _wait_result(unit)
    unit.stop()
    assert outcome == Outcome.COMPLETE
    assert end == "wrap"


def test_aborted_turn_is_not_node_done():
    """Regression (2026-08-13 quality-run): a supervisor-aborted assistant turn
    (message with `error`, or `completed` set but `finish` present and not
    'stop') must NOT advance the node on its truncated draft. Only a normal
    finish ('stop'/'' or a legacy client without a finish attribute) counts."""
    class AbortClient(FakeClient):
        def send_message(self, sid, text, agent):
            if agent == "reviewer":
                super().send_message(sid, text, agent)
            else:
                # turn has `completed` ts (opencode sets it on abort) but a
                # non-normal finish -> interrupted, must not advance
                self.msgs[sid] = [Message(
                    "assistant", "truncated draft mid-method",
                    completed="1786008000000", reply="truncated draft mid-method",
                    finish=None)]
    s = Settings(monitor_enabled=False, poll_sec=0.1)
    sm = load_regime()
    client = AbortClient()
    unit = WorkflowUnit(s, sm, client, poll_sec=0.1)
    unit.start()
    unit.submit("任务")
    # the interrupted turn is not done; without a normal turn the workflow
    # must not reach COMPLETE within the timeout -> it times out (no advance)
    res = _wait_result(unit, timeout=1.5)
    unit.stop()
    assert res is None or res[0] != Outcome.COMPLETE


def test_error_message_is_not_node_done():
    """A developer message carrying an error (abort surfaced as message.error)
    must not be treated as a finished node."""
    class ErrClient(FakeClient):
        def send_message(self, sid, text, agent):
            if agent == "reviewer":
                super().send_message(sid, text, agent)
            else:
                self.msgs[sid] = [Message(
                    "assistant", "partial", error="aborted",
                    completed="1786008000000", reply="partial", finish=None)]
    s = Settings(monitor_enabled=False, poll_sec=0.1)
    sm = load_regime()
    client = ErrClient()
    unit = WorkflowUnit(s, sm, client, poll_sec=0.1)
    unit.start()
    unit.submit("任务")
    res = _wait_result(unit, timeout=1.5)
    unit.stop()
    assert res is None or res[0] != Outcome.COMPLETE


def test_large_report_logs_report_len_warn():
    """Regression (D): an abnormally large agent report must be audited
    (report_len_warn event) so out-of-control output is visible in the journal
    instead of silently advancing."""
    from regime_driver.app.reporter import Reporter

    class BigClient(FakeClient):
        def send_message(self, sid, text, agent):
            if agent == "reviewer":
                super().send_message(sid, text, agent)
            else:
                big = "x" * 30000  # exceeds default report_len_warn=20000
                self.msgs[sid] = [Message("assistant", big,
                                          completed="1786008000000", reply=big)]
    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        rep = Reporter(journal_path=Path(td) / "j.jsonl")
        s = Settings(monitor_enabled=False, poll_sec=0.1)
        sm = load_regime()
        client = BigClient()
        unit = WorkflowUnit(s, sm, client, poll_sec=0.1, reporter=rep)
        unit.start()
        unit.submit("任务")
        outcome, end, detail = _wait_result(unit)
        unit.stop()
        assert outcome == Outcome.COMPLETE
        recs = rep.journal_slice()
        assert any(r["event_type"] == "report_len_warn" for r in recs)


def test_judge_waits_for_new_reply_not_stale():
    """A failed judge verdict must NOT be re-parsed/re-dispatched every poll.

    The real client accumulates messages, so once a judge reply exists it stays
    the 'latest' until a newer one arrives. Without tracking the last-processed
    reply, the workflow re-parses the stale (failed) verdict on every poll and
    re-dispatches a duplicate send_message POST to the same session — starving
    the dispatch pool and stalling. Regression: exactly one re-prompt, then the
    workflow waits for and consumes the corrected reply.
    """
    from regime_driver.core.models import Node, NodeType

    class StaleWindowClient(FakeClient):
        def __init__(self, bad, good, delay_reads=5):
            super().__init__()
            self.bad, self.good = bad, good
            self.delay_reads = delay_reads
            self.reviewer_prompts = 0
            self._reads_after_bad = 0
            self._good_appended = False

        def send_message(self, sid, text, agent):
            if agent == "reviewer":
                m = re.search(r"当前节点：(\w+)", text)
                node = m.group(1) if m else "judge"
                self.reviewer_prompts += 1
                # first prompt yields the bad reply; re-prompts overwrite with bad
                # again until the good reply is appended by read_messages below
                if node == "judge" and not self._good_appended:
                    self.msgs[sid] = [Message("assistant", json.dumps(self.bad))]
            else:
                self.msgs.setdefault(sid, []).append(
                    Message("assistant", "work done\n[WORK_DONE]"))

        def read_messages(self, sid):
            msgs = list(self.msgs.get(sid, []))
            # the corrected reply only appears after a 'stale window' of reads
            if (not self._good_appended
                    and msgs
                    and '"bogus"' in msgs[-1].text):
                self._reads_after_bad += 1
                if self._reads_after_bad > self.delay_reads:
                    msgs.append(Message("assistant", json.dumps(self.good)))
                    self._good_appended = True
                    self.msgs[sid] = msgs
            return msgs

    produce = Node(id="produce", desc="produce", type=NodeType.AGENT, next="judge")
    judge = Node(id="judge", desc="judge", type=NodeType.JUDGE,
                 role="reviewer", next="end")
    end = Node(id="end", desc="end", type=NodeType.AGENT, next=None)
    s = Settings(monitor_enabled=False, poll_sec=0.1, max_reviewer_retries=2)
    sm = _sm([produce, judge, end])
    bad = {"node": "judge", "verdict": "advance", "action": "advance",
           "next_state": "bogus", "confidence": 0.9, "reason": "bad target"}
    good = {"node": "judge", "verdict": "advance", "action": "advance",
            "next_state": "end", "confidence": 0.9, "reason": "ok"}
    client = StaleWindowClient(bad, good)
    unit = WorkflowUnit(s, sm, client, poll_sec=0.05)
    unit.start()
    unit.submit("task")
    outcome, end_node, detail = _wait_result(unit)
    unit.stop()
    assert outcome == Outcome.COMPLETE, f"expected COMPLETE, got {outcome}: {detail}"
    assert end_node == "end"
    # initial prompt + exactly one retry; NOT a re-prompt on every stale poll
    assert client.reviewer_prompts == 2, f"judge re-prompted {client.reviewer_prompts}x"


def test_dispatch_records_failures_for_diagnostics():
    """A send that keeps failing is recorded so the error/timeout detail surfaces it."""
    class FailClient(FakeClient):
        def send_message(self, sid, text, agent):
            raise RuntimeError("provider down")

    s = Settings(monitor_enabled=False, poll_sec=0.1, default_deadline_sec=1)
    sm = load_regime()
    unit = WorkflowUnit(s, sm, FailClient(), poll_sec=0.05)
    unit.start()
    unit.submit("任务")
    outcome, _, detail = _wait_result(unit, timeout=5)
    unit.stop()
    assert outcome == Outcome.TIMEOUT
    assert "dispatch failures" in (detail or "")
    assert "provider down" in (detail or "")


def test_dispatch_serializes_prior_post():
    """Dispatch must await the prior node's POST before sending the next.

    Regression for the E2E judge stall: the streaming POST /message returns
    LATER than the completion marker the workflow advances on, so without
    awaiting the prior future the dispatch pool saturates and the next node's
    prompt queues forever (session looks busy-with-no-output -> false stall).
    This asserts at most ONE send_message is in flight at a time.
    """
    import threading
    from regime_driver.core.statechart import Bus

    class ConcurrentClient(FakeClient):
        def __init__(self):
            super().__init__()
            self._active = 0
            self._max_active = 0
            self._lock = threading.Lock()

        def send_message(self, sid, text, agent):
            with self._lock:
                self._active += 1
                self._max_active = max(self._max_active, self._active)
            super().send_message(sid, text, agent)  # completion marker appears now
            time.sleep(0.3)  # ...but the POST stays open past it (trailing)
            with self._lock:
                self._active -= 1

    s = Settings(monitor_enabled=False, poll_sec=0.1)
    sm = load_regime()
    client = ConcurrentClient()
    unit = WorkflowUnit(s, sm, client, poll_sec=0.05, bus=Bus())
    unit.start()
    unit.submit("实现反转函数")  # code_workflow: 3+ developer nodes
    outcome, _, _ = _wait_result(unit)
    unit.stop()
    assert outcome == Outcome.COMPLETE
    assert client._max_active == 1, \
        f"expected serialized dispatch, saw {client._max_active} concurrent POSTs"


def test_per_node_wait_timeout():
    """A node that never completes is marked TIMEOUT after default_deadline_sec."""
    class NeverClient(FakeClient):
        def send_message(self, sid, text, agent):
            pass  # never produce a reply -> node never completes
    s = Settings(monitor_enabled=False, poll_sec=0.1, default_deadline_sec=1)
    sm = load_regime()
    client = NeverClient()
    unit = WorkflowUnit(s, sm, client, poll_sec=0.05)
    unit.start()
    unit.submit("任务")
    outcome, end, detail = _wait_result(unit, timeout=5)
    unit.stop()
    assert outcome == Outcome.TIMEOUT
    assert "default_deadline_sec" in detail


def test_heartbeat_updates_per_step():
    """The workflow's blackboard heartbeat reflects liveness (refreshes each step)."""
    from regime_driver.core.statechart import Bus
    from regime_driver.app.blackboard import Blackboard

    bus = Bus()
    bb = Blackboard(publisher=lambda ev, f: bus.publish("blackboard", ev, f))
    bus.blackboard = bb
    s = Settings(monitor_enabled=False, poll_sec=0.1)
    sm = load_regime()
    client = FakeClient()
    unit = WorkflowUnit(s, sm, client, poll_sec=0.1, bus=bus)
    unit.start()
    unit.submit("任务")
    time.sleep(0.5)
    hb1 = unit.bus.blackboard.get("workflow.heartbeat")
    time.sleep(0.6)
    hb2 = unit.bus.blackboard.get("workflow.heartbeat")
    unit.stop()
    assert hb1 and hb2 and hb2 > hb1  # heartbeat advanced -> workflow is alive


def test_dispatch_is_non_blocking():
    """_dispatch returns immediately even if the remote send would block."""
    import threading
    import time as _t

    class SlowClient(FakeClient):
        def send_message(self, sid, text, agent):
            _t.sleep(0.5)  # simulate a slow pending model response
            super().send_message(sid, text, agent)

    s = Settings(monitor_enabled=False)
    sm = load_regime()
    client = SlowClient()
    unit = WorkflowUnit(s, sm, client, poll_sec=0.05)
    t0 = _t.monotonic()
    unit._dispatch("s1", "prompt", "developer")  # must return immediately
    elapsed = _t.monotonic() - t0
    assert elapsed < 0.4, f"_dispatch blocked for {elapsed:.2f}s"
    # wait for the pool to actually deliver, then ensure it reached the client
    deadline = _t.time() + 2
    while not client.msgs and _t.time() < deadline:
        _t.sleep(0.02)
    unit.stop()
    assert client.msgs, "dispatched send never reached the client"


def _sig(unit, src, kind, payload):
    from regime_driver.core.statechart import Signal
    return Signal(kind, src, unit.id, payload)


# --- tool / route / gate dispatch (custom flows) ---------------------------

class NodeClient(FakeClient):
    """Returns [WORK_DONE] with a per-node report; no reviewer involvement."""

    def __init__(self, reports):
        super().__init__()
        self.reports = reports  # node_id -> report text

    def send_message(self, sid, text, agent):
        m = re.search(r"【当前节点：(\w+)】", text)
        node = m.group(1) if m else "?"
        rep = self.reports.get(node, "")
        self.msgs[sid] = [Message("assistant", f"{rep}\n[WORK_DONE]")]


def _sm(nodes):
    from regime_driver.core.models import Flow, FlowEntry, Regime, RegimeMeta
    flow = Flow(nodes={n.id: n for n in nodes})
    regime = Regime(version="t", meta=RegimeMeta(), flows={"f": flow},
                    entry=FlowEntry(flow="f", start_node=nodes[0].id))
    from regime_driver.core.state_machine import StateMachine
    return StateMachine(regime)


def _wu(nodes, reports, overrides=None):
    from regime_driver.core.models import Node  # noqa
    s = Settings(monitor_enabled=False, poll_sec=0.1, **(overrides or {}))
    sm = _sm(nodes)
    client = NodeClient(reports)
    unit = WorkflowUnit(s, sm, client, poll_sec=0.1)
    return unit, client


def test_workflow_tool_node_runs_and_advances():
    from regime_driver.core.models import Node, NodeType
    tool = Node(id="t", desc="check", type=NodeType.TOOL, tool="have_report", next="end")
    end = Node(id="end", desc="done", type=NodeType.AGENT, next=None)
    unit, client = _wu([tool, end], {"end": "no report here"})
    unit.start()
    unit.submit("ctx")
    outcome, end_node, detail = _wait_result(unit)
    unit.stop()
    assert outcome == Outcome.COMPLETE
    assert unit._env["ok"] is False  # no report at tool time


def test_workflow_route_branches_to_match():
    from regime_driver.core.models import Node, NodeType
    p = Node(id="p", desc="produce", type=NodeType.AGENT, next="r")
    route = Node(id="r", desc="route", type=NodeType.ROUTE,
                 branches=[{"when": "report contains 'good'", "goto": "ok_node"}], next="bad_node")
    ok_node = Node(id="ok_node", desc="ok", type=NodeType.AGENT, next=None)
    bad_node = Node(id="bad_node", desc="bad", type=NodeType.AGENT, next=None)
    unit, client = _wu([p, route, ok_node, bad_node], {"p": "good work here"})
    unit.start()
    unit.submit("ctx")
    outcome, end_node, detail = _wait_result(unit)
    unit.stop()
    assert outcome == Outcome.COMPLETE
    assert end_node == "ok_node"  # routed to the branch, not the fallback


def test_workflow_route_falls_through_to_next():
    from regime_driver.core.models import Node, NodeType
    p = Node(id="p", desc="produce", type=NodeType.AGENT, next="r")
    route = Node(id="r", desc="route", type=NodeType.ROUTE,
                 branches=[{"when": "report contains 'good'", "goto": "ok_node"}], next="bad_node")
    ok_node = Node(id="ok_node", desc="ok", type=NodeType.AGENT, next=None)
    bad_node = Node(id="bad_node", desc="bad", type=NodeType.AGENT, next=None)
    unit, client = _wu([p, route, ok_node, bad_node], {"p": "nothing changed"})
    unit.start()
    unit.submit("ctx")
    outcome, end_node, detail = _wait_result(unit)
    unit.stop()
    assert end_node == "bad_node"  # no branch matched -> next


def test_workflow_gate_blocked_when_no_branch_matches():
    from regime_driver.core.models import Node, NodeType
    p = Node(id="p", desc="produce", type=NodeType.AGENT, next="g")
    gate = Node(id="g", desc="gate", type=NodeType.GATE,
                branches=[{"when": "report contains 'pass'", "goto": "end"}], next="end")
    end = Node(id="end", desc="done", type=NodeType.AGENT, next=None)
    unit, client = _wu([p, gate, end], {"p": "nothing changed"})
    unit.start()
    unit.submit("ctx")
    outcome, end_node, detail = _wait_result(unit)
    unit.stop()
    assert outcome == Outcome.BLOCKED
    assert "not satisfied" in detail


def test_workflow_gate_passes_when_branch_matches():
    from regime_driver.core.models import Node, NodeType
    p = Node(id="p", desc="produce", type=NodeType.AGENT, next="g")
    gate = Node(id="g", desc="gate", type=NodeType.GATE,
                branches=[{"when": "report contains 'pass'", "goto": "end"}], next="end")
    end = Node(id="end", desc="done", type=NodeType.AGENT, next=None)
    unit, client = _wu([p, gate, end], {"p": "pass ok"})
    unit.start()
    unit.submit("ctx")
    outcome, end_node, detail = _wait_result(unit)
    unit.stop()
    assert outcome == Outcome.COMPLETE
    assert end_node == "end"


def test_workflow_workspace_hint_in_instruction():
    from regime_driver.core.models import Node, NodeType
    unit, client = _wu([Node(id="a", desc="work", type=NodeType.AGENT, next=None)], {})
    instr = unit._build_instruction("a", "ctx", "developer")
    assert "code" in instr


# --- transition policy (anchor / rotate) -----------------------------------

def _transition_unit(roles, node_role="reviewer"):
    from regime_driver.core.models import Node, NodeType
    from regime_driver.core.state_machine import StateMachine
    n = Node(id="a", desc="", role=node_role, type=NodeType.AGENT, next=None)
    s = Settings(monitor_enabled=False, poll_sec=0.1)
    sm = _sm([n])
    client = FakeClient()
    unit = WorkflowUnit(s, sm, client, roles=roles, poll_sec=0.1)
    unit.sessions.ensure(node_role, "t")
    return unit


def test_workflow_anchor_transition_pins_session():
    from regime_driver.core.policy import RolePolicy, TransitionDecision
    from regime_driver.core.role import Role, RoleRegistry
    roles = RoleRegistry().register(
        Role(id="reviewer", agent="reviewer",
             policy=RolePolicy(transition_mode=TransitionDecision.ANCHOR)))
    unit = _transition_unit(roles)
    old_sid = unit.sessions.get("reviewer").session_id
    unit._apply_transition("a", "dummy")
    assert unit.sessions.get("reviewer").session_id == old_sid  # anchored


def test_workflow_transition_rotate_rotates_session():
    from regime_driver.core.policy import RolePolicy, TransitionDecision
    from regime_driver.core.role import Role, RoleRegistry
    roles = RoleRegistry().register(
        Role(id="reviewer", agent="reviewer",
             policy=RolePolicy(transition_mode=TransitionDecision.ROTATE)))
    unit = _transition_unit(roles)
    old_sid = unit.sessions.get("reviewer").session_id
    unit._apply_transition("a", "dummy")
    assert unit.sessions.get("reviewer").session_id != old_sid  # rotated
    assert any('"kind":"brain_normal"' in s[1] for s in unit.client.sent)