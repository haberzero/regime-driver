"""Tests for the WorkflowUnit (governed state machine driving a flow)."""

import json
import re
import time

from regime_driver.app.workflow_unit import WorkflowUnit, _PH_AGENT, _PH_JUDGE, _PH_HUMAN
from regime_driver.core.models import Outcome
from regime_driver.core.statechart import SignalKind
from regime_driver.infra.ledger import Ledger
from regime_driver.infra.regime_loader import load_regime
from regime_driver.infra.settings import Settings

# successor map for the real code_workflow: judge node -> valid advance target
SUCC = {"design": "implement", "test": "wrap"}


class Message:
    def __init__(self, role, text="", error=None, completed="now", reply=None,
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
        self.aborted = []

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
        return self.tokens.get(sid, (0, 0))

    def abort_session(self, sid):
        self.aborted.append(sid)


def _make(overrides=None):
    s = Settings(monitor_enabled=False, **(overrides or {}))
    sm = load_regime()
    client = FakeClient()
    unit = WorkflowUnit(s, sm, client, poll_sec=0.1)
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
    # WORK_PLAN9: a watchdog STOP must also abort the in-flight session, so the
    # model stops producing orphan work (files/artifacts) after the workflow is
    # declared blocked.
    assert client.aborted, "STOP must abort the in-flight session (prevent orphans)"
    assert len(client.aborted) == 1


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
    unit = WorkflowUnit(s, sm, client, poll_sec=0.1)
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
    unit = WorkflowUnit(s, sm, client, poll_sec=0.1)
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
    unit = WorkflowUnit(s, sm, client, poll_sec=0.1)
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
    unit = WorkflowUnit(s, sm, client, poll_sec=0.1)
    unit.start()
    unit.submit("task")
    outcome, end_node, detail = _wait_result(unit)
    unit.stop()
    assert outcome == Outcome.COMPLETE, f"expected COMPLETE, got {outcome}: {detail}"
    assert end_node == "end"
    # initial prompt + exactly one retry; NOT a re-prompt on every stale poll
    assert client.reviewer_prompts == 2, f"judge re-prompted {client.reviewer_prompts}x"


def test_judge_waits_for_completed_not_partial():
    """The judge must NOT parse a verdict from a streaming PARTIAL reply —
    it waits for the turn's `completed` marker. The 2026-08-15 nightly:
    payment_ledger died with "reviewer gate exhausted" because a partial reply
    (no `completed`) was judged, extract_json returned None, the dedup key
    consumed the partial, and the COMPLETE reply (parseable) was never judged."""
    class PartialThenCompleteClient(FakeClient):
        def __init__(self):
            super().__init__()
            self.partial_judged = False
            self.reviewer_prompts = 0

        def send_message(self, sid, text, agent):
            if agent == "reviewer":
                self.reviewer_prompts += 1
                verdict = {"node": "judge", "verdict": "advance",
                           "action": "advance", "next_state": "end",
                           "confidence": 0.9, "reason": "ok"}
                # stream a PARTIAL (not completed) reply first, then the complete one
                self.msgs[sid] = [
                    Message("assistant", json.dumps(verdict)[:20], completed=None),
                    Message("assistant", json.dumps(verdict), completed="done"),
                ]
            else:
                self.msgs[sid] = [Message("assistant", "work done\n[WORK_DONE]")]

    from regime_driver.core.models import Node, NodeType
    produce = Node(id="produce", desc="produce", type=NodeType.AGENT, next="judge")
    judge = Node(id="judge", desc="judge", type=NodeType.JUDGE,
                 role="reviewer", next="end")
    end = Node(id="end", desc="end", type=NodeType.AGENT, next=None)
    s = Settings(monitor_enabled=False, poll_sec=0.1, max_reviewer_retries=2)
    sm = _sm([produce, judge, end])
    client = PartialThenCompleteClient()
    unit = WorkflowUnit(s, sm, client, poll_sec=0.1)
    unit.start()
    unit.submit("task")
    outcome, end_node, detail = _wait_result(unit, timeout=10)
    unit.stop()
    # the partial (no completed) reply is skipped; the complete reply is judged
    assert outcome == Outcome.COMPLETE, f"got {outcome}: {detail}"
    assert end_node == "end"
    # no re-prompt storms on the partial — the judge waits for completion
    assert client.reviewer_prompts == 1, f"judge re-prompted {client.reviewer_prompts}x"


def test_judge_skips_abort_draft_with_no_finish():
    """A completed-but-no-finish message is an ABORT draft (truncated text) and
    must never be judged — the pause-abort residue in a judge turn (review
    warning: `_latest_assistant` scanning past a partial could otherwise return
    the abort draft as a verdict candidate)."""
    class AbortDraftClient(FakeClient):
        def send_message(self, sid, text, agent):
            if agent == "reviewer":
                verdict = {"node": "judge", "verdict": "advance",
                           "action": "advance", "next_state": "end",
                           "confidence": 0.9, "reason": "ok"}
                self.msgs[sid] = [
                    # abort draft: completed ts but no finish sentinel
                    Message("assistant", json.dumps(verdict), completed="done",
                            finish=None),
                    # then the real complete reply
                    Message("assistant", json.dumps(verdict), completed="done",
                            finish="stop"),
                ]
            else:
                self.msgs[sid] = [Message("assistant", "work done\n[WORK_DONE]")]

    from regime_driver.core.models import Node, NodeType
    produce = Node(id="produce", desc="produce", type=NodeType.AGENT, next="judge")
    judge = Node(id="judge", desc="judge", type=NodeType.JUDGE,
                 role="reviewer", next="end")
    end = Node(id="end", desc="end", type=NodeType.AGENT, next=None)
    s = Settings(monitor_enabled=False, poll_sec=0.1, max_reviewer_retries=2)
    sm = _sm([produce, judge, end])
    unit = WorkflowUnit(s, sm, AbortDraftClient(), poll_sec=0.1)
    unit.start()
    unit.submit("task")
    outcome, end_node, detail = _wait_result(unit, timeout=10)
    unit.stop()
    # the abort draft is skipped; the finished reply is judged -> COMPLETE
    assert outcome == Outcome.COMPLETE, f"got {outcome}: {detail}"
    assert end_node == "end"


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
    unit = WorkflowUnit(s, sm, client, poll_sec=0.1)
    unit.start()
    unit.submit("任务")
    outcome, end, detail = _wait_result(unit, timeout=5)
    unit.stop()
    assert outcome == Outcome.TIMEOUT
    assert "default_deadline_sec" in detail
    # WORK_PLAN9: a per-node timeout must also abort the in-flight session to
    # stop orphan work (same rationale as a watchdog STOP).
    assert client.aborted, "node timeout must abort the in-flight session"


def test_per_node_deadline_grace_for_busy_session():
    """A wall-clock deadline must NOT kill a session that is still busy
    server-side: the expiry extends (deadline_grace) and defers true-stall
    detection to the SSE-liveness watchdog."""
    class BusyClient(FakeClient):
        def send_message(self, sid, text, agent):
            pass  # never produce a reply, but stays busy server-side
        def session_status(self, sid):
            return "busy"
    s = Settings(monitor_enabled=False, poll_sec=0.1, default_deadline_sec=1)
    sm = load_regime()
    client = BusyClient()
    unit = WorkflowUnit(s, sm, client, poll_sec=0.1)
    unit.start()
    unit.submit("任务")
    # 3+ grace windows: a kill-on-wall-clock behavior would have fired at ~1s
    outcome = _wait_result(unit, timeout=3.2)
    unit.stop()
    assert outcome is None, f"busy session must survive wall-clock expiry, got {outcome}"
    assert client.aborted == []


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
    unit = WorkflowUnit(s, sm, client, poll_sec=0.1)
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


def test_agent_node_skill_injected_into_instruction():
    """WORK_PLAN8 stage-2: a node's declared skill must be injected into the
    WORKER (agent) instruction, not only into reviewer prompts. Previously the
    agent-node skill field in regime.json was dead config — `_build_instruction`
    ignored it, so implement/wrap could never carry developer-quality."""
    from regime_driver.core.models import Node, NodeType
    unit, client = _wu(
        [Node(id="a", desc="work", type=NodeType.AGENT,
              skill="developer-quality", next=None)], {})
    instr = unit._build_instruction("a", "ctx", "developer")
    assert "应用技能（developer-quality）" in instr
    assert "Developer 质量自律" in instr


def test_agent_node_skill_missing_fails_loudly():
    """A node declaring a nonexistent skill is a config error: building the
    instruction must raise (fail loudly), not silently degrade."""
    from regime_driver.core.models import Node, NodeType
    from regime_driver.infra.skill_loader import SkillNotFoundError
    unit, client = _wu(
        [Node(id="a", desc="work", type=NodeType.AGENT,
              skill="no-such-skill", next=None)], {})
    try:
        unit._build_instruction("a", "ctx", "developer")
        assert False, "expected SkillNotFoundError"
    except SkillNotFoundError:
        pass


# --- WORK_PLAN13 node capability boundary + marker --------------------------

def test_readonly_node_instruction_forbids_writes():
    from regime_driver.core.models import Node, NodeType
    unit, client = _wu(
        [Node(id="a", desc="understand", type=NodeType.AGENT, readonly=True,
              next=None)], {})
    instr = unit._build_instruction("a", "ctx", "developer")
    assert "只读" in instr
    assert "禁止修改/创建/删除任何文件" in instr


def test_writable_node_instruction_has_no_readonly_block():
    from regime_driver.core.models import Node, NodeType
    unit, client = _wu(
        [Node(id="a", desc="implement", type=NodeType.AGENT, readonly=False,
              next=None)], {})
    instr = unit._build_instruction("a", "ctx", "developer")
    assert "节点能力：本节点为【只读】" not in instr


def test_instruction_asks_for_work_done_marker():
    from regime_driver.core.models import Node, NodeType
    unit, client = _wu(
        [Node(id="a", desc="work", type=NodeType.AGENT, next=None)], {})
    instr = unit._build_instruction("a", "ctx", "developer")
    assert "[WORK_DONE]" in instr


def test_verify_evidence_fed_to_judge_prompt(monkeypatch):
    from regime_driver.core.models import Node, NodeType
    from regime_driver.app.verify import VerifyResult
    # judge node declaring a whitelisted verify command -> the driver runs it
    # and stores the runtime evidence for the judge prompt. The docker exec is
    # mocked (no real container in unit tests).
    unit, client = _wu(
        [Node(id="a", desc="understand", type=NodeType.AGENT, next="t"),
         Node(id="t", desc="test", role="reviewer", type=NodeType.JUDGE,
              skill="code-review", verify="docker exec {container} pytest -q",
              next=None)],
        {}, {"verify_enabled": True})
    monkeypatch.setattr(
        "regime_driver.app.workflow_unit.run_verify",
        lambda cmd, container="opencode-worker", timeout=300.0: VerifyResult(
            ok=True, rc=0, stdout_tail="42 passed", stderr_tail="",
            elapsed=0.5, timed_out=False))
    unit.sessions.ensure("developer", "t")
    unit._context = "ctx"
    unit._developer_report = "63 passed"
    unit._valid_targets = {"wrap"}
    unit._enter_judge("t")
    assert unit._verify_evidence is not None
    assert "42 passed" in unit._verify_evidence
    assert not unit._verify_failed


def test_verify_skipped_when_disabled():
    from regime_driver.core.models import Node, NodeType
    unit, client = _wu(
        [Node(id="a", desc="understand", type=NodeType.AGENT, next="t"),
         Node(id="t", desc="test", role="reviewer", type=NodeType.JUDGE,
              skill="code-review", verify="docker exec {container} pytest -q", next=None)],
        {}, {"verify_enabled": False})
    unit.sessions.ensure("developer", "t")
    unit._context = "ctx"
    unit._valid_targets = {"wrap"}
    unit._enter_judge("t")
    assert unit._verify_evidence is None
    assert not unit._verify_failed


def test_verify_failure_blocks_advance_deterministically():
    """B3: a failed runtime verify injects a blocking issue so the gate
    deterministically refuses advance even if the reviewer papered it over."""
    from regime_driver.core.models import Node, NodeType
    from regime_driver.app.reviewer import Reviewer
    from regime_driver.core.state_machine import StateMachine
    from regime_driver.infra.regime_loader import load_regime
    sm = load_regime()
    reviewer = Reviewer(None, "s1", "reviewer", sm, skills_dir=str(
        __import__("pathlib").Path(__file__).parent.parent / "workflow-regime" / "skills"))
    verdict = {"node": "test", "verdict": "advance", "action": "advance",
               "next_state": "wrap", "confidence": 0.9, "reason": "ok", "issues": []}
    import json as _json
    result = reviewer.parse_reply(
        _json.dumps(verdict), "test", {"wrap"},
        extra_issues=[{"severity": "blocking",
                       "summary": "运行时验证未通过（宿主 verify 命令 rc!=0/失败），未解决不得 advance"}])
    assert not result.ok
    assert "blocking" in result.gate.reason


def test_context_handover_forced_at_hard_threshold():
    """WORK_PLAN13: with a configured context policy at hard fraction, entering
    the next node must rotate the session and log a context_handover event."""
    from regime_driver.core.models import Node, NodeType
    overrides = {
        "context_handover_policy_json": '{"soft_fraction": 0.4, "hard_fraction": 0.5, "min_continue_nodes": 2}',
        "context_limit_tokens": 100000,
    }
    unit, client = _wu(
        [Node(id="a", desc="understand", type=NodeType.AGENT, readonly=True,
              next="b"),
         Node(id="b", desc="implement", type=NodeType.AGENT, next=None)],
        {}, overrides)
    unit.sessions.ensure("developer", "t")
    old_sid = unit.sessions.get("developer").session_id
    # simulate a near-full session
    client.tokens[old_sid] = (60000, 10000)  # 70% of 100k -> hard threshold
    unit._context = "ctx"
    # record what gets sent (the fake overwrites msgs with a canned reply)
    sent_texts = []

    def _record_send(sid, text, agent):
        sent_texts.append(text)
        client.msgs[sid] = [Message("assistant", text)]

    client.send_message = _record_send
    unit._check_session_capacity("b")
    new_sid = unit.sessions.get("developer").session_id
    assert new_sid != old_sid  # rotated
    assert any("【上下文交接】" in t for t in sent_texts)  # readable handover opening


def test_external_abort_agent_blocks_not_hangs():
    """An externally-aborted agent session (supervisor T2 kill, no pause) must
    terminate as BLOCKED instead of polling a dead session forever."""
    from regime_driver.core.models import Node, NodeType, Outcome
    unit, client = _wu(
        [Node(id="a", desc="work", type=NodeType.AGENT, next=None)], {})
    sid = unit.sessions.ensure("developer", "t").session_id
    unit._wait_sid = sid
    unit._wait_role = "developer"
    unit._phase = _PH_AGENT
    unit._paused = False
    client.msgs[sid] = [Message("assistant", "draft", error="MessageAbortedError",
                                completed=str(time.time()), finish=None)]
    unit._step_agent()
    assert unit._result is not None
    assert unit._result[0] == Outcome.BLOCKED
    assert "externally aborted" in unit._result[2]


def test_paused_external_abort_not_blocked():
    """A paused session (in-process watchdog PAUSE aborts the session but sets
    _paused=True first) must NOT be treated as a dead session."""
    from regime_driver.core.models import Node, NodeType, Outcome
    unit, client = _wu(
        [Node(id="a", desc="work", type=NodeType.AGENT, next=None)], {})
    sid = unit.sessions.ensure("developer", "t").session_id
    unit._wait_sid = sid
    unit._wait_role = "developer"
    unit._phase = _PH_AGENT
    unit._paused = True
    client.msgs[sid] = [Message("assistant", "draft", error="MessageAbortedError",
                                completed=str(time.time()), finish=None)]
    unit._step_agent()
    assert unit._result is None  # still waiting for RESUME


def test_latest_abort_distinguishes_transient_from_abort():
    """W3: `_latest_abort` classifies only genuine aborts as dead-session
    sentinels; a transient message error (model HTTP / rate limit) is NOT."""
    from regime_driver.core.models import Node, NodeType
    unit, client = _wu(
        [Node(id="a", desc="work", type=NodeType.AGENT, next=None)], {})
    unit.sessions.ensure("developer", "t")
    # transient error -> not an abort; surfaced as the transient error
    msgs_t = [Message("assistant", "x", error="HTTP 500 on POST /message", reply="x")]
    assert unit._latest_abort(msgs_t) is False
    assert unit._latest_transient_error(msgs_t) == "HTTP 500 on POST /message"
    # abort error -> IS an abort
    msgs_a = [Message("assistant", "x", error="MessageAbortedError", reply="x")]
    assert unit._latest_abort(msgs_a) is True
    assert unit._latest_transient_error(msgs_a) is None
    # real-worker abort shape (completed ts, no finish) -> abort regardless
    msgs_s = [Message("assistant", "x", completed="1786008000000", finish=None)]
    assert unit._latest_abort(msgs_s) is True


def test_transient_error_not_blocked_keeps_polling():
    """W3: a TRANSIENT message error must NOT block the run as a dead session —
    the workflow keeps polling (bounded by the node deadline)."""
    from regime_driver.core.models import Node, NodeType, Outcome
    unit, client = _wu(
        [Node(id="a", desc="work", type=NodeType.AGENT, next=None)], {})
    sid = unit.sessions.ensure("developer", "t").session_id
    unit._wait_sid = sid
    unit._wait_role = "developer"
    unit._phase = _PH_AGENT
    unit._paused = False
    client.msgs[sid] = [Message("assistant", "partial",
                                error="HTTP 500 on POST /message", reply="partial")]
    unit._step_agent()
    assert unit._result is None  # not blocked — keeps polling, not BLOCKED


def test_transient_error_audited_in_journal():
    """W3: a transient message error is surfaced as a `message_transient_error`
    audit event (throttled per distinct error), never silently swallowed."""
    from pathlib import Path

    from regime_driver.app.reporter import Reporter
    from regime_driver.core.models import Node, NodeType

    unit, client = _wu([Node(id="a", desc="work", type=NodeType.AGENT, next=None)], {})
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        rep = Reporter(journal_path=Path(td) / "j.jsonl", project_id="t")
        unit.reporter = rep
        sid = unit.sessions.ensure("developer", "t").session_id
        unit._wait_sid = sid
        unit._wait_role = "developer"
        unit._phase = _PH_AGENT
        unit._paused = False
        client.msgs[sid] = [Message("assistant", "partial",
                                    error="HTTP 500 on POST /message", reply="partial")]
        unit._step_agent()
        assert unit._result is None
        recs = rep.journal_slice()
        assert any(r["event_type"] == "message_transient_error" for r in recs)
        assert any("HTTP 500" in r.get("detail", {}).get("err", "") for r in recs)
        # second poll with the SAME error is throttled (no duplicate audit spam)
        unit._step_agent()
        n = sum(1 for r in rep.journal_slice() if r["event_type"] == "message_transient_error")
        assert n == 1
        rep.close()


def test_judge_transient_error_not_parsed_as_verdict():
    """W3: a transient error on the judge session is NOT a verdict candidate —
    the judge keeps polling instead of mis-parsing the error text."""
    import json as _json

    from regime_driver.core.models import Node, NodeType

    unit, client = _wu(
        [Node(id="a", desc="work", type=NodeType.AGENT, next="t"),
         Node(id="t", desc="test", role="reviewer", type=NodeType.JUDGE, next=None)], {})
    unit.sessions.ensure("developer", "t")
    sid = unit.sessions.ensure("reviewer", "t").session_id
    unit._wait_sid = sid
    unit._wait_role = "reviewer"
    unit._node = "t"
    unit._valid_targets = {"wrap"}
    unit._phase = _PH_JUDGE
    unit._paused = False
    # a transient-error message whose text looks like a verdict must NOT be parsed
    verdict_like = _json.dumps({"node": "t", "verdict": "advance", "action": "advance",
                                "next_state": "wrap", "confidence": 0.9})
    client.msgs[sid] = [Message("assistant", verdict_like,
                                error="rate limit exceeded, retry later", reply=verdict_like)]
    assert unit._latest_assistant(client.msgs[sid]) is None  # error msg skipped


def test_transient_error_persistent_times_out_via_node_deadline():
    """W3: a session that NEVER recovers from a transient error is bounded by the
    per-node deadline -> TIMEOUT (not a hang, not a false BLOCK)."""
    from regime_driver.core.models import Node, NodeType, Outcome

    class AlwaysErr(NodeClient):
        def send_message(self, sid, text, agent):
            self.sent.append((sid, text, agent))
            self.msgs[sid] = [Message("assistant", "partial",
                                      error="HTTP 500 on POST /message", reply="partial")]

    s = Settings(monitor_enabled=False, poll_sec=0.1, default_deadline_sec=1)
    sm = _sm([Node(id="a", desc="work", type=NodeType.AGENT, next=None)])
    client = AlwaysErr({})
    unit = WorkflowUnit(s, sm, client, poll_sec=0.1)
    unit.start()
    unit.submit("任务")
    outcome, end, detail = _wait_result(unit, timeout=3)
    unit.stop()
    assert outcome == Outcome.TIMEOUT
    assert "default_deadline_sec" in detail


def _ask_human_unit(nodes, overrides=None):
    from regime_driver.app.statechart_runtime import Runtime
    rt = Runtime(enforce_invariants=False)
    unit, client = _wu(nodes, {}, overrides)
    unit.bus = rt.bus
    unit._context = "ctx"
    return unit, client, rt


def _human_verdict(node="t", question="确认放行？"):
    from regime_driver.core.models import ReviewerVerdict
    from regime_driver.app.reviewer import ReviewerResult
    verdict = ReviewerVerdict(node=node, verdict="blocked", action="ask_human",
                              human_question=question, confidence=0.8,
                              reason="需人工确认")
    return ReviewerResult(verdict=verdict)


def test_ask_human_yes_advances_and_consumes_decision():
    """Phase-4: an ask_human checkpoint waits for the dialog's YES and then
    advances; the decision is consumed (one-shot)."""
    from regime_driver.core.models import Node, NodeType, Outcome
    unit, client, rt = _ask_human_unit(
        [Node(id="a", desc="work", type=NodeType.AGENT, next="t"),
         Node(id="t", desc="test", role="reviewer", type=NodeType.JUDGE, next=None)])
    unit._node = "t"
    unit._valid_targets = set()
    unit._handle_verdict(_human_verdict())
    assert unit._phase == _PH_HUMAN
    assert rt.blackboard.get("workflow.human_ask") == "确认放行？"
    assert rt.blackboard.get("workflow.human_waiting") is True
    # dialog decides YES -> advance; t is terminal -> COMPLETE
    rt.blackboard.set("workflow.human_decision", {"answer": "yes", "comment": "ok"})
    unit._step_human()
    assert unit._result is not None and unit._result[0] == Outcome.COMPLETE
    # decision consumed AND all checkpoint keys cleared (B3): never listed pending again
    assert rt.blackboard.get("workflow.human_decision") is None
    assert rt.blackboard.get("workflow.human_waiting") is None
    assert rt.blackboard.get("workflow.human_ask") is None


def test_ask_human_no_routes_developer_rework():
    """Phase-4: a dialog NO sends the developer back for rework with the
    comment, then re-judges the node."""
    from regime_driver.core.models import Node, NodeType
    unit, client, rt = _ask_human_unit(
        [Node(id="a", desc="work", type=NodeType.AGENT, next="t"),
         Node(id="t", desc="test", role="reviewer", type=NodeType.JUDGE, next=None)])
    unit._node = "t"
    unit._valid_targets = set()
    unit._handle_verdict(_human_verdict())
    assert unit._phase == _PH_HUMAN
    rt.blackboard.set("workflow.human_decision", {"answer": "no", "comment": "重做"})
    unit._step_human()
    assert unit._phase == _PH_AGENT  # back to the developer for rework
    assert unit._rejudge == "t"      # the node is re-judged after rework


def test_ask_human_timeout_defaults_to_block():
    """Phase-4: without a dialog decision the configured timeout default applies
    (block = the safest unattended default)."""
    from regime_driver.core.models import Node, NodeType, Outcome
    unit, client, rt = _ask_human_unit(
        [Node(id="a", desc="work", type=NodeType.AGENT, next="t"),
         Node(id="t", desc="test", role="reviewer", type=NodeType.JUDGE, next=None)],
        overrides={"human_confirm_timeout_sec": 1})
    unit._node = "t"
    unit._valid_targets = set()
    unit._handle_verdict(_human_verdict())
    assert unit._phase == _PH_HUMAN
    unit._phase_started = time.time() - 5  # already past the 1s timeout
    unit._step_human()
    assert unit._result is not None and unit._result[0] == Outcome.BLOCKED
    assert "human confirmation timed out" in unit._result[2]


def test_resume_window_own_abort_sentinel_not_blocked():
    """B1 regression: after a PAUSE abort + RESUME, the old abort sentinel is
    still the latest message until the session's reply materializes. The
    workflow must NOT treat its own pause sentinel as an external dead session."""
    from regime_driver.core.models import Node, NodeType, Outcome
    unit, client = _wu(
        [Node(id="a", desc="work", type=NodeType.AGENT, next=None)], {})
    sid = unit.sessions.ensure("developer", "t").session_id
    unit._wait_sid = sid
    unit._wait_role = "developer"
    unit._phase = _PH_AGENT
    unit._node = "a"
    # simulate PAUSE: workflow aborts its own session and marks _own_abort
    unit._paused = True
    client.msgs[sid] = [Message("assistant", "draft", error="MessageAbortedError",
                                completed=str(time.time()), finish=None)]
    unit._abort_waiting_session("pause")
    unit._own_abort = True
    # simulate RESUME: unpause; the sentinel is still the latest message
    unit._paused = False
    unit._step_agent()
    assert unit._result is None  # own pause sentinel -> keep polling, not BLOCKED
    # once a real reply arrives the flag clears and flow continues (node completes)
    client.msgs[sid] = [Message("assistant", "work done\n[WORK_DONE]",
                                completed=str(time.time()), finish="stop")]
    unit._step_agent()
    assert not unit._own_abort  # flag cleared on non-abort message
    assert unit._result is not None  # the done reply advanced the flow


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
    # WORK_PLAN13: the fresh session receives the readable handover opening
    assert any("【上下文交接】" in s[1] for s in unit.client.sent)