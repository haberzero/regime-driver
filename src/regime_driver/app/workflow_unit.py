"""Workflow as a peer state machine unit (app layer, full refactor).

The final architecture makes the workflow itself a *governed* statechart unit
that runs in the same Runtime as the watchdog (watchdog) unit. It drives the
regime flow node by node from a **single-threaded mixed loop**: in one thread it
(a) drains inbound signals (STOP from the watchdog, etc.), (b) polls the
session it dispatched work to, and (c) steps the node machine. Because the work
is dispatched to remote sessions (which generate asynchronously), the loop stays
free between polls to react to control signals — this is the "single-thread
mixed loop" principle from ARCHITECTURE-statechart-network §5.2.1.

The unit reports its alive session state to the watchdog via REPORT signals,
and the watchdog can interrupt it with a STOP signal (abort).
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from ..core.branching import ConditionError, resolve_branch
from ..core.handoff import Handoff, detect_loop
from ..core.models import NodeType, Outcome
from ..core.policy import TransitionDecision, workspace_for
from ..core.role import RoleRegistry, default_roles
from ..core.segment import SegmentParser
from ..core.statechart import Signal, SignalKind
from ..core.state_machine import StateMachine
from ..core.tools import UnknownToolError, run_tool
from ..infra.ledger import Ledger
from ..infra.opencode import OpenCodeClient
from ..infra.settings import Settings
from ..infra.skill_loader import SkillNotFoundError, load_skill
from ..infra.task_control import TaskControl
from .reviewer import Reviewer
from .session_lifecycle import SessionLifecycle, SessionRotator
from .session_manager import SessionRegistry
from .statechart_runtime import ThreadedUnit

# internal states
_ST_IDLE = "idle"
_ST_RUNNING = "running"
_ST_DONE = "done"
_ST_ABORTED = "aborted"
_ST_ERROR = "error"

# phases while running a node
_PH_NONE = "none"
_PH_AGENT = "agent_wait"   # agent node dispatched, polling its session
_PH_JUDGE = "judge_wait"   # judge node dispatched, polling the reviewer session


class WorkflowUnit(ThreadedUnit):
    """A governed state machine that drives one regime flow on remote sessions."""

    def __init__(
        self,
        settings: Settings,
        state_machine: StateMachine,
        client: OpenCodeClient,
        ledger: Ledger | None = None,
        reporter: "Reporter | None" = None,
        roles: RoleRegistry | None = None,
        unit_id: str = "workflow",
        run_id: str | None = None,
        bus=None,
        poll_sec: float | None = None,
    ) -> None:
        super().__init__(unit_id, bus)
        # run_id distinguishes THIS run in the report bus from prior runs, so a
        # single `regime run` does not accumulate under a constant wf_id.
        # Defaults to the unit id (e.g. per-workflow ids in a cluster).
        self.run_id = run_id or self.id
        self.settings = settings
        self.sm = state_machine
        self.client = client
        self.ledger = ledger
        self.reporter = reporter
        self.roles = roles or default_roles()
        self.poll_sec = poll_sec or settings.poll_sec
        self.segment_parser = SegmentParser(state_machine.regime.meta.work_done_marker)
        self.sessions = SessionRegistry(client, agent_by_role={
            rid: self.roles.get(rid).agent for rid in self.roles.ids()
        })
        self.reviewers: dict[str, Reviewer] = {}
        self.task_control = (
            TaskControl(settings.task_control_dir) if settings.task_control_dir else None
        )
        self.session_lifecycle = SessionLifecycle(settings, client, self.roles)
        self.session_rotator = SessionRotator(client, self.sessions)
        # dispatch pool: blocking send_message (up to the client timeout) runs on
        # a worker thread so the mixed loop never blocks and stays responsive to
        # STOP even while a prompt is being generated remotely.
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="dispatch")
        self._active_dispatch = None  # future of the in-flight dispatch POST
        self._dispatch_errors: list[str] = []  # last dispatch failures (for diagnostics)

        # run state
        self._state = _ST_IDLE
        self._phase = _PH_NONE
        self._node: str | None = None
        self._wait_sid: str | None = None
        self._wait_role: str | None = None
        self._goal = ""
        self._context = ""
        self._developer_report: str | None = None
        self._extra_context: str | None = None
        self._valid_targets: set[str] = set()
        self._rounds: list[tuple[str, str]] = []
        self._judge_attempts = 0
        self._retry_feedback: str | None = None
        self._node_count = 0
        self._anchor = "developer"
        self._env: dict = {"context": "", "report": "", "ok": True, "message": ""}
        self._result: tuple[Outcome, str | None, str | None] | None = None
        self._monitor_stop: str | None = None
        self._rejudge: str | None = None   # judge node awaiting a rework re-judge
        self._dialogue_rounds = 0          # ask_developer -> rework cycles
        self._last_judged_key: tuple | None = None  # identity of the judge reply already processed
        self._start_time: float | None = None
        self._phase_started: float | None = None  # when the current wait phase began

        # control handlers
        self.register(SignalKind.STOP, self._on_stop)
        self.register(SignalKind.PAUSE, lambda s: None)
        self.register(SignalKind.RESUME, lambda s: None)
        self.register(SignalKind.NOTIFY, self._on_submit)  # start a run

    # -- lifecycle (ThreadedUnit override) -----------------------------------

    def stop(self, timeout: float = 2.0) -> None:
        super().stop(timeout)
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _run(self) -> None:
        """Single-threaded mixed loop: drain signals + step the node machine."""
        last_poll = 0.0
        while not self._stop.is_set():
            self._drain_signals()
            if self._state == _ST_RUNNING:
                now = time.monotonic()
                if now - last_poll >= self.poll_sec:
                    last_poll = now
                    try:
                        self._step()
                    except Exception as exc:
                        self._log("workflow_step_error", node=self._node, err=str(exc))
                        self._state = _ST_ERROR
                        self._result = (Outcome.ERROR, self._node, f"workflow step error: {exc}")
                        break
            if self._state in (_ST_DONE, _ST_ABORTED, _ST_ERROR):
                if self._result is not None:
                    self._log("outcome", node=self._result[1],
                              outcome=self._result[0].value,
                              detail=self._result[2] or "")
                break
            time.sleep(min(self.poll_sec, 0.1))

    def _drain_signals(self) -> None:
        """Process inbound signals (STOP from the watchdog, etc.)."""
        while True:
            try:
                sig = self._q.get_nowait()
            except Exception:
                break
            try:
                self.on_signal(sig)
            except Exception as exc:
                # never kill the loop, but never swallow silently either: audit it
                self._log("signal_handler_error", kind=str(sig.kind), err=str(exc))

    # -- control handlers -----------------------------------------------------

    def _on_stop(self, signal: Signal) -> None:
        self._monitor_stop = signal.get("reason") or "watchdog stop"
        self._cancel_running()

    def _cancel_running(self) -> None:
        if self._state == _ST_RUNNING:
            # Abort the in-flight session so the model stops producing orphan
            # work the moment the watchdog declares a stall/loop. If we only
            # mark BLOCKED, the worker keeps generating (a STOP interrupts the
            # workflow, not the session) — writing files, burning budget, and
            # polluting artifact collection with post-mortem writes.
            self._abort_waiting_session(reason=self._monitor_stop)
            self._state = _ST_ABORTED
            self._result = (Outcome.BLOCKED, self._node, f"monitor: {self._monitor_stop}")

    def _abort_waiting_session(self, reason: str | None = None) -> None:
        """Abort whatever session the workflow is currently waiting on (best-effort)."""
        if self._wait_sid is None:
            return
        try:
            self.client.abort_session(self._wait_sid)
            self._log("monitor_abort", session=self._wait_sid,
                      reason=reason or self._monitor_stop or "abort")
        except Exception as exc:
            self._log("monitor_abort_error", session=self._wait_sid, err=str(exc))

    # -- public start ---------------------------------------------------------

    def submit(self, context: str, title: str = "regime-workflow") -> None:
        """Request the flow to run on the workflow's own thread (non-blocking).

        Enqueues a start signal so the initial dispatch happens on the workflow
        thread, not the caller's (avoids blocking the caller on a long send).
        """
        self.deliver(Signal(SignalKind.NOTIFY, "user", self.id,
                            {"context": context, "title": title}))

    def _on_submit(self, signal: Signal) -> None:
        self._begin(signal.get("context", ""), signal.get("title", "regime-workflow"))

    def _begin(self, context: str, title: str) -> None:
        self._goal = context
        self._context = context
        self._env = {"context": context, "report": "", "ok": True, "message": ""}
        self._anchor = self._anchor_role()
        self.sessions.ensure(self._anchor, title)
        self._node = self.sm.flow_path()[0]
        self._state = _ST_RUNNING
        self._node_count = 0
        self._start_time = time.time()
        self._write_metrics()
        self._enter_node(self._node)

    def result(self) -> tuple[Outcome, str | None, str | None] | None:
        return self._result

    # -- stepping -------------------------------------------------------------

    def _dispatch(self, sid: str, text: str, agent: str, retries: int = 3) -> None:
        """Dispatch a prompt/send to the pool; never blocks the mixed loop.

        The remote session generates asynchronously; this unit observes progress
        by polling the session. A send failure is retried with backoff so a slow
        judge/agent is not dropped; the watchdog's heartbeat/stall detection
        is the final backstop.

        Crucial: the streaming POST /message only returns once the turn finishes,
        which is LATER than the `message.completed` / `[WORK_DONE]` marker the
        workflow uses to advance. If we dispatched the next node without waiting
        for that POST to return, the previous node's POST would still be holding a
        worker thread, and with a small pool the next dispatch would queue forever
        (the session looks "busy, no output" -> false stall kill). So we await the
        prior POST future first, waiting for true turn completion before freeing a
        pool slot for the next node. The wait stays STOP-responsive (drains signals
        and aborts early on a control state).
        """
        self._await_prior_dispatch()

        def _send() -> None:
            for attempt in range(retries + 1):
                try:
                    self.client.send_message(sid, text, agent)
                    return
                except Exception as exc:
                    self._log("dispatch_error", session=sid, attempt=attempt, err=str(exc))
                    if attempt == 0:
                        self._dispatch_errors.append(f"{agent}: {exc}")
                    if attempt < retries:
                        time.sleep(2.0 * (attempt + 1))  # backoff before retry

        self._active_dispatch = self._executor.submit(_send)

    def _await_prior_dispatch(self) -> None:
        """Wait for the previous node's POST future, staying STOP-responsive."""
        fut = self._active_dispatch
        if fut is None:
            return
        while not fut.done():
            self._drain_signals()
            if self._state in (_ST_ABORTED, _ST_ERROR, _ST_DONE):
                return  # a control signal interrupted the wait
            time.sleep(0.05)
        # consume a possible exception so it doesn't surface as an unhandled warning
        try:
            fut.result()
        except Exception:
            pass

    def _step(self) -> None:
        self._touch_heartbeat()
        if self._phase != _PH_NONE:
            # per-node wait timeout: never hang forever on a stuck idle session
            if (self._phase_started
                    and time.time() - self._phase_started > self.settings.default_deadline_sec):
                self._abort_waiting_session(
                    reason=f"node timeout after {self.settings.default_deadline_sec}s")
                self._state = _ST_ERROR
                self._result = (Outcome.TIMEOUT, self._node,
                                self._with_dispatch_diag(
                                    f"node '{self._node}' exceeded default_deadline_sec "
                                    f"({self.settings.default_deadline_sec}s)"))
                return
        if self._phase == _PH_AGENT:
            self._step_agent()
        elif self._phase == _PH_JUDGE:
            self._step_judge()

    def _touch_heartbeat(self) -> None:
        """Update the liveness heartbeat + diagnostics each step (per-workflow key)."""
        bb = self.bus.blackboard if self.bus is not None else None
        if bb is not None:
            p = f"{self.id}."
            bb.update(**{
                f"{p}heartbeat": time.time(),
                f"{p}wait_sid": self._wait_sid,
                f"{p}waiting_s": round(time.time() - self._phase_started, 1)
                if self._phase_started else 0,
            })

    def _begin_wait(self, phase: str) -> None:
        self._phase = phase
        self._phase_started = time.time()

    def _enter_node(self, node_id: str) -> None:
        node = self.sm.node(node_id)
        self._log("node_enter", node=node_id, type=node.type.value, role=node.role)
        self._node = node_id
        self._node_count += 1
        self._write_metrics()
        # fresh node: reset per-node interrogation state (re-judge does not call this)
        self._dialogue_rounds = 0
        self._rounds = []
        self._extra_context = None
        if self._node_count > self.settings.max_total_nodes:
            self._state = _ST_ABORTED
            self._result = (Outcome.BLOCKED, node_id,
                            f"exceeded max_total_nodes ({self.settings.max_total_nodes})")
            return
        if node.type == NodeType.AGENT:
            self._enter_agent(node_id)
        elif node.type == NodeType.JUDGE:
            self._enter_judge(node_id)
        else:  # tool / route / gate: deterministic, transfer immediately
            self._enter_deterministic(node)

    def _enter_agent(self, node_id: str) -> None:
        role = self.sm.node(node_id).role
        sid = self.sessions.ensure(role).session_id
        try:
            instruction = self._build_instruction(node_id, self._context, role)
            self._dispatch(sid, instruction, self.sessions.agent_for(role))
        except Exception as exc:
            self._state = _ST_ERROR
            self._result = (Outcome.ERROR, node_id, str(exc))
            return
        self._wait_sid = sid
        self._wait_role = role
        self._begin_wait(_PH_AGENT)

    def _enter_judge(self, node_id: str) -> None:
        role = self.sm.node(node_id).role
        reviewer = self._get_reviewer(role)
        self._valid_targets = set(self.sm.successors(node_id))
        self._begin_wait(_PH_JUDGE)
        self._wait_sid = reviewer.session_id
        self._wait_role = role
        self._judge_attempts = 0
        self._retry_feedback = None
        self._last_judged_key = None
        self._send_judge_prompt(reviewer, node_id)

    def _send_judge_prompt(self, reviewer: Reviewer, node_id: str) -> None:
        prompt = reviewer.prompt_for(
            node_id, self._context, self._developer_report,
            self._extra_context, self._retry_feedback, self._valid_targets,
        )
        try:
            self._dispatch(reviewer.session_id, prompt, reviewer.agent)
        except Exception as exc:
            self._state = _ST_ERROR
            self._result = (Outcome.ERROR, node_id, str(exc))

    def _step_agent(self) -> None:
        try:
            messages = self.client.read_messages(self._wait_sid)
        except Exception as exc:
            self._state = _ST_ERROR
            self._result = (Outcome.ERROR, self._node, str(exc))
            return
        done, report = self._latest_agent_done(messages)
        if done:
            rlen = len(report or "")
            self._log("node_done", node=self._node, outcome="complete",
                      report_len=rlen)
            if rlen > self.settings.report_len_warn:
                # an abnormally large report is a weak signal that the model
                # output outgrew control (e.g. pasted history / truncated-draft
                # loop). Audit it so it is visible in the journal, but do not
                # block: the reviewer judge still verifies the deliverable.
                self._log("report_len_warn", node=self._node,
                          report_len=rlen,
                          threshold=self.settings.report_len_warn)
            self._developer_report = report
            if report is not None:
                self._env["report"] = report
            self._record_worklog(self._node, report)
            if self._rejudge is not None:
                judge_node = self._rejudge
                self._rejudge = None
                self._enter_judge(judge_node)  # re-judge after rework
            else:
                self._advance()
        self._report_to_watchdog()

    def _latest_agent_done(self, messages) -> tuple[bool, str | None]:
        """Detect whether the developer finished this node's work.

        Primary signal: opencode's native turn-finished marker
        (`info.time.completed` on the latest assistant message). This is more
        reliable than asking the model to emit a magic string. A `[WORK_DONE]`
        marker in the reply is kept as a fallback for short/scripted tasks.

        A message interrupted by a supervisor abort (carries `error`, or has a
        `completed` ts but `finish=None` — the abort sentinel observed on the
        real 1.18.11 worker) is NOT a finished node: its reply is a truncated
        draft, not a deliverable, so it must not advance. Every other finish
        ('stop', '', token-limit 'length', ...) advances; a truncated-but-
        finished report is still handed to the reviewer judge which decides.
        """
        for m in reversed(messages):
            if getattr(m, "role", None) != "assistant":
                continue
            if getattr(m, "error", None):
                # abort surfaced as a message error
                return False, None
            reply = (getattr(m, "reply", "") or "").strip() \
                or (getattr(m, "text", "") or "").strip()
            # native completion: the assistant turn finished
            if getattr(m, "completed", None):
                finish = getattr(m, "finish", "stop")
                if finish is None:
                    # real-client abort: completed ts set but no finish sentinel
                    return False, None
                if reply and self.segment_parser.has_segment_end(reply):
                    return True, self.segment_parser.extract_report(reply)
                return True, reply or None
            # fallback: explicit marker in a still-open reply (short/scripted)
            if reply and self.segment_parser.has_segment_end(reply):
                return True, self.segment_parser.extract_report(reply)
            return False, None
        return False, None

    def _step_judge(self) -> None:
        try:
            messages = self.client.read_messages(self._wait_sid)
        except Exception as exc:
            self._state = _ST_ERROR
            self._result = (Outcome.ERROR, self._node, str(exc))
            return
        latest = self._latest_assistant(messages)
        if latest is None:
            self._report_to_watchdog()
            return
        # skip a reply we have already processed: the judge session accumulates
        # messages, so _latest_text alone would re-parse the previous (failure)
        # reply on every poll while a re-prompt is still generating — spamming
        # duplicate send_message POSTs and starving the dispatch pool. Only act
        # once per distinct reply. Prefer the stable message id (real client);
        # fall back to the reply text for clients without an id (test doubles).
        mid = getattr(latest, "id", None)
        key = ("id", mid) if mid else (
            "text", (getattr(latest, "reply", "") or "") + (getattr(latest, "text", "") or ""))
        if key == self._last_judged_key:
            self._report_to_watchdog()
            return
        self._last_judged_key = key
        text = (getattr(latest, "reply", "") or "") or (getattr(latest, "text", "") or "")
        reviewer = self._get_reviewer(self._wait_role)
        result = reviewer.parse_reply(text, self._node, self._valid_targets)
        if result.ok:
            self._handle_verdict(result)
        else:
            self._judge_attempts += 1
            self._retry_feedback = result.error or (
                result.gate.reason if result.gate else "unknown"
            )
            if self._judge_attempts > self.settings.max_reviewer_retries:
                self._state = _ST_ERROR
                self._result = (Outcome.ERROR, self._node, "reviewer gate exhausted")
            else:
                self._send_judge_prompt(reviewer, self._node)
        self._report_to_watchdog()

    def _handle_verdict(self, result) -> None:
        verdict = result.verdict
        action = verdict.action
        self._log("reviewer_verdict", node=self._node, verdict=verdict.verdict,
                  action=action, confidence=verdict.confidence)
        if action == "advance":
            target = verdict.next_state
            if target is None and not self._valid_targets:
                # terminal judge: advance to end-of-flow (COMPLETE)
                self._log("advance", to="<end>")
                self._phase = _PH_NONE
                self._phase_started = None
                self._advance(None)
                return
            if target in self._valid_targets:
                self._log("advance", to=target)
                self._phase = _PH_NONE
                self._phase_started = None
                self._advance(target)
                return
            self._state = _ST_ERROR
            self._result = (Outcome.ERROR, self._node, f"bad advance target '{target}'")
            return
        if action == "ask_developer":
            self._dialogue_rounds += 1
            if self._dialogue_rounds > self.settings.max_dialogue_rounds:
                self._state = _ST_ERROR
                self._result = (Outcome.ERROR, self._node, "reviewer dialogue rounds exhausted")
                return
            inquiry = Handoff.reviewer_inquiry(
                criticisms=[verdict.reason] if verdict.reason else [],
                required_rework=verdict.message_to_developer or "",
                flow_node=self._node,
            )
            self._log("reviewer_inquiry", node=self._node, msg=inquiry.summary)
            self._rounds.append((inquiry.inquiry_text(), self._developer_report or ""))
            if detect_loop(self._rounds, self.settings.convergence_max_identical):
                self._state = _ST_ABORTED
                self._result = (Outcome.BLOCKED, self._node,
                                "reviewer/developer interrogation is looping")
                return
            work_sid = self.sessions.ensure("developer").session_id
            try:
                self._dispatch(work_sid, inquiry.inquiry_text(),
                               self.sessions.agent_for("developer"))
            except Exception as exc:
                self._state = _ST_ERROR
                self._result = (Outcome.ERROR, self._node, str(exc))
                return
            self._rejudge = self._node
            self._wait_sid = work_sid
            self._begin_wait(_PH_AGENT)
            return
        if action == "request_context":
            self._extra_context = verdict.context_requested
            self._send_judge_prompt(self._get_reviewer(self._wait_role), self._node)
            return
        if action == "abort_session":
            self.sessions.abort("developer")
            self._state = _ST_ABORTED
            self._result = (Outcome.ABORTED, self._node, verdict.reason)
            return
        if action == "report_user":
            self._state = _ST_DONE
            self._result = (Outcome.HUMAN, self._node, verdict.reason)
            return
        self._state = _ST_ERROR
        self._result = (Outcome.ERROR, self._node, f"unknown action '{action}'")

    def _advance(self, next_node: str | None = None) -> None:
        if next_node is None:
            next_node = self.sm.next(self._node)
        if next_node is None:
            self._state = _ST_DONE
            self._result = (Outcome.COMPLETE, self._node, None)
            return
        self._apply_transition(self._node, next_node)
        if self._state == _ST_ABORTED:  # transition may have been interrupted
            return
        self.sessions.advance_round(self._anchor)
        self._check_session_capacity(self.sessions.get(self._anchor), next_node)
        self._phase = _PH_NONE
        self._phase_started = None
        self._enter_node(next_node)

    def _enter_deterministic(self, node) -> None:
        node_id = node.id
        if node.type == NodeType.TOOL:
            try:
                tresult = run_tool(node, self._env.get("context", self._context),
                                   self._env.get("report", self._developer_report or ""))
            except UnknownToolError as exc:
                self._state = _ST_ERROR
                self._result = (Outcome.ERROR, node_id, str(exc))
                return
            self._env["ok"] = tresult.ok
            self._env["message"] = tresult.message
            self._log("tool_done", node=node_id, tool=node.tool, ok=tresult.ok)
            target = self._resolve_det(node)
        else:  # route / gate
            try:
                target = resolve_branch(node, self._env)
            except ConditionError as exc:
                self._state = _ST_ERROR
                self._result = (Outcome.ERROR, node_id, str(exc))
                return
            if target is None and node.type == NodeType.GATE:
                self._state = _ST_ABORTED
                self._result = (Outcome.BLOCKED, node_id, f"gate '{node_id}' not satisfied")
                return
            if target is None:
                target = self.sm.next(node_id)
        if target is not None and target not in self.sm.flow.nodes:
            self._state = _ST_ERROR
            self._result = (Outcome.ERROR, node_id, f"bad branch target '{target}'")
            return
        self._advance(target)

    def _resolve_det(self, node) -> str | None:
        try:
            target = resolve_branch(node, self._env)
        except ConditionError:
            return None
        if target is not None and target in self.sm.flow.nodes:
            return target
        return self.sm.next(node.id)

    # -- helpers --------------------------------------------------------------

    def _report_to_watchdog(self) -> None:
        """Feed the alive session's state to the watchdog as a REPORT.

        A REPORT must always be sent; a read failure must never silently drop it
        (that would blind the watchdog into a false stall/loop verdict). Failures
        are recorded as auditable events and surfaced in the REPORT payload.
        """
        if self.bus is None or self._wait_sid is None:
            return
        payload: dict = {"session_id": self._wait_sid, "status": None,
                         "output": 0, "reasoning": 0, "latest_text": "",
                         "report_error": None}
        try:
            payload["status"] = self.client.session_status(self._wait_sid)
            # reasoning AND output both count as liveness: a long "thinking"
            # phase streams reasoning tokens before any text lands (deepseek
            # spends minutes reasoning for hard tasks). Dropping reasoning here
            # would blind the watchdog into a false stall on a healthy session.
            reasoning, output = self.client.session_tokens(self._wait_sid)
            payload["output"] = output
            payload["reasoning"] = reasoning
        except Exception as exc:
            payload["report_error"] = f"status/tokens: {exc}"
            self._log("report_error", session=self._wait_sid, err=str(exc))
        try:
            payload["latest_text"] = self._latest_text(
                self.client.read_messages(self._wait_sid))
        except Exception as exc:
            payload["report_error"] = (
                (payload["report_error"] + "; " if payload["report_error"] else "")
                + f"read: {exc}")
            self._log("report_error", session=self._wait_sid, err=str(exc))
        self.send("watchdog", SignalKind.REPORT, payload)

    def _get_reviewer(self, role_id: str) -> Reviewer:
        if role_id not in self.reviewers:
            rev = self.sessions.ensure(role_id)
            role = self.roles.get(role_id)
            self.reviewers[role_id] = Reviewer(
                client=self.client, session_id=rev.session_id, agent=role.agent,
                state_machine=self.sm,
                skills_dir=role.skills_dir or self.settings.skills_dir,
                max_retries=self.settings.max_reviewer_retries,
            )
        return self.reviewers[role_id]

    def _anchor_role(self) -> str:
        for nid in self.sm.flow_path():
            if self.sm.node(nid).type == NodeType.AGENT:
                return self.sm.node(nid).role
        return "developer"

    def _build_instruction(self, node_id, context, role_id) -> str:
        node = self.sm.node(node_id)
        ws = workspace_for(role_id or node.role)
        ws_hint = (
            f"\n工作区：你只在 {ws['work_dir']} 目录内工作变更，可读可见目录：{', '.join(ws['visible'])}，"
            f"可写目录：{', '.join(ws['writable'])}。"
        )
        parts = [
            f"【当前节点：{node_id}】{node.desc}",
            f"任务上下文：{context}",
            ws_hint,
        ]
        skill = getattr(node, "skill", None)
        if skill:
            # a node's declared skill is injected into the WORKER prompt (same
            # mechanism as judge nodes): it gives the executing developer the
            # methodology/self-check for THIS node (e.g. developer-quality).
            # A missing skill is a config error -> fail loudly, not silently
            # degrade the instruction.
            skill_text = load_skill(skill, self.settings.skills_dir)
            parts.append(f"应用技能（{skill}）：\n{skill_text}")
        parts.append(
            "请完成本节点工作。完成后直接用你的最终回复给出简短结构化汇报："
            "改动文件 / 测试命令与结果 / 技术债 / 待决点。"
        )
        return "\n".join(parts)

    def _latest_text(self, messages) -> str:
        text = ""
        for m in reversed(messages):
            if getattr(m, "role", None) == "assistant" and getattr(m, "text", "").strip():
                text = m.text
                break
        return text

    def _latest_assistant(self, messages):
        """Return the newest assistant message carrying a non-empty reply, else None."""
        for m in reversed(messages):
            if getattr(m, "role", None) != "assistant":
                continue
            if (getattr(m, "reply", "") or getattr(m, "text", "") or "").strip():
                return m
        return None

    def _record_worklog(self, node_id, report) -> None:
        if self.task_control is None:
            return
        self.task_control.init("worklog")
        self.task_control.append("worklog", f"节点 {node_id} 完成。\n{report or ''}")

    def _apply_transition(self, prev_node, next_node) -> None:
        # the transition DECISION is a deterministic invariant: a failure here is a
        # config/policy bug and must fail the run visibly (fail-fast), not be
        # swallowed. The rotate/handover that follows is best-effort and logged.
        prev_role = self.sm.node(prev_node).role
        policy = self.roles.get(prev_role).policy
        decision = policy.on_node_transition(prev_node, next_node, self._env)
        self._log("transition", from_node=prev_node, to_node=next_node,
                  role=prev_role, decision=decision.value)
        if decision == TransitionDecision.ROTATE:
            try:
                self.session_rotator.rotate_with_handover(
                    prev_role, summary=f"节点 {prev_node} 完成，流转到 {next_node}。",
                    handoff_kind="normal")
            except Exception as exc:
                self._log("transition_rotate_error", from_node=prev_node,
                          to_node=next_node, err=str(exc))

    def _check_session_capacity(self, dev, node_id) -> bool:
        try:
            if dev is None or not self.session_lifecycle.should_self_assess(dev):
                return False
            usage = round(self.session_lifecycle.capacity_used(dev), 2)
            assessment = None
            if not self.session_lifecycle.policy_for(dev.role).is_urgent(usage):
                assessment = self.session_lifecycle.assess(dev, usage)
            action = self.session_lifecycle.decide(dev, assessment, usage)
            if action in ("handoff_now", "rotate"):
                self.session_rotator.rotate_with_handover(
                    dev.role,
                    summary=f"节点 {node_id}，上下文已用 {usage:.0%}，切换会话。",
                    handoff_kind="urgent" if action == "handoff_now" else "normal")
                return True
        except Exception as exc:
            self._log("session_capacity_error", node=node_id, err=str(exc))
        return False

    def _log(self, event, **fields) -> None:
        if self.ledger is not None:
            self.ledger.append(event, **fields)
        if self.reporter is not None:
            self.reporter.ingest(
                kind=event,
                wf_id=self.run_id,
                sm_id=self.sm.flow_name,
                session_id=fields.get("session_id") or self._wait_sid,
                node=fields.get("node"),
                outcome=fields.get("outcome"),
                event_type=event,
                detail=dict(fields),
            )

    def record_outcome(self, outcome: str, *, node: str | None = None,
                       detail: str = "") -> None:
        """Publicly record a run outcome to ledger/reporter (D1).

        Used by the driver when the run is externally cut short (e.g. driver
        timeout) — the workflow thread never reached a terminal state, so it
        would otherwise write no outcome event and the run would vanish from
        the report bus.
        """
        self._log("outcome", node=node or self._node,
                  outcome=outcome, detail=detail)

    def _with_dispatch_diag(self, detail: str) -> str:
        """Append recent dispatch failures to a result detail for user visibility."""
        if not self._dispatch_errors:
            return detail
        return detail + " (dispatch failures: " + "; ".join(self._dispatch_errors[-5:]) + ")"

    def _write_metrics(self) -> None:
        """Publish live runtime metrics to the shared blackboard (if any)."""
        bb = self.bus.blackboard if self.bus is not None else None
        if bb is None:
            return
        now = time.time()
        p = f"{self.id}."  # per-workflow key prefix (multi-workflow isolation)
        bb.update(**{
            f"{p}node": self._node,
            f"{p}phase": self._phase,
            f"{p}node_count": self._node_count,
            f"{p}state": self._state,
            f"{p}heartbeat": now,
            f"{p}start_time": self._start_time or now,
            f"{p}wait_sid": self._wait_sid,
            f"{p}waiting_s": round(time.time() - self._phase_started, 1) if self._phase_started else 0,
        })