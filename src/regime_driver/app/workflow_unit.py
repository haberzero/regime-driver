"""Workflow as a peer state machine unit (app layer, full refactor).

The final architecture makes the workflow itself a *governed* statechart unit
that runs in the same Runtime as the constitution (watchdog) unit. It drives the
regime flow node by node from a **single-threaded mixed loop**: in one thread it
(a) drains inbound signals (STOP from the constitution, etc.), (b) polls the
session it dispatched work to, and (c) steps the node machine. Because the work
is dispatched to remote sessions (which generate asynchronously), the loop stays
free between polls to react to control signals — this is the "single-thread
mixed loop" principle from ARCHITECTURE-statechart-network §5.2.1.

The unit reports its alive session state to the constitution via REPORT signals,
and the constitution can interrupt it with a STOP signal (abort).
"""

from __future__ import annotations

import time

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
        roles: RoleRegistry | None = None,
        unit_id: str = "workflow",
        bus=None,
        poll_sec: float | None = None,
    ) -> None:
        super().__init__(unit_id, bus)
        self.settings = settings
        self.sm = state_machine
        self.client = client
        self.ledger = ledger
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

        # control handlers
        self.register(SignalKind.STOP, self._on_stop)
        self.register(SignalKind.PAUSE, lambda s: None)
        self.register(SignalKind.RESUME, lambda s: None)

    # -- lifecycle (ThreadedUnit override) -----------------------------------

    def _run(self) -> None:
        """Single-threaded mixed loop: drain signals + step the node machine."""
        last_poll = 0.0
        while not self._stop.is_set():
            self._drain_signals()
            if self._state == _ST_RUNNING:
                now = time.monotonic()
                if now - last_poll >= self.poll_sec:
                    last_poll = now
                    self._step()
            if self._state in (_ST_DONE, _ST_ABORTED, _ST_ERROR):
                break
            time.sleep(min(self.poll_sec, 0.1))

    def _drain_signals(self) -> None:
        """Process inbound signals (STOP from the constitution, etc.)."""
        while True:
            try:
                sig = self._q.get_nowait()
            except Exception:
                break
            try:
                self.on_signal(sig)
            except Exception:
                pass

    # -- control handlers -----------------------------------------------------

    def _on_stop(self, signal: Signal) -> None:
        self._monitor_stop = signal.get("reason") or "constitution stop"
        self._cancel_running()

    def _cancel_running(self) -> None:
        if self._state == _ST_RUNNING:
            self._state = _ST_ABORTED
            self._result = (Outcome.BLOCKED, self._node, f"monitor: {self._monitor_stop}")

    # -- public start ---------------------------------------------------------

    def submit(self, context: str, title: str = "regime-workflow") -> None:
        """Begin running the flow on a fresh anchor session (non-blocking)."""
        self._goal = context
        self._context = context
        self._env = {"context": context, "report": "", "ok": True, "message": ""}
        self._anchor = self._anchor_role()
        self.sessions.ensure(self._anchor, title)
        self._node = self.sm.flow_path()[0]
        self._state = _ST_RUNNING
        self._node_count = 0
        self._enter_node(self._node)

    def result(self) -> tuple[Outcome, str | None, str | None] | None:
        return self._result

    # -- stepping -------------------------------------------------------------

    def _step(self) -> None:
        if self._phase == _PH_AGENT:
            self._step_agent()
        elif self._phase == _PH_JUDGE:
            self._step_judge()

    def _enter_node(self, node_id: str) -> None:
        node = self.sm.node(node_id)
        self._log("node_enter", node=node_id, type=node.type.value, role=node.role)
        self._node = node_id
        self._node_count += 1
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
        instruction = self._build_instruction(node_id, self._context, role)
        try:
            self.client.send_message(sid, instruction, self.sessions.agent_for(role))
        except Exception as exc:
            self._state = _ST_ERROR
            self._result = (Outcome.ERROR, node_id, str(exc))
            return
        self._wait_sid = sid
        self._wait_role = role
        self._phase = _PH_AGENT

    def _enter_judge(self, node_id: str) -> None:
        role = self.sm.node(node_id).role
        reviewer = self._get_reviewer(role)
        self._valid_targets = set(self.sm.successors(node_id))
        self._phase = _PH_JUDGE
        self._wait_sid = reviewer.session_id
        self._wait_role = role
        self._judge_attempts = 0
        self._retry_feedback = None
        self._send_judge_prompt(reviewer, node_id)

    def _send_judge_prompt(self, reviewer: Reviewer, node_id: str) -> None:
        prompt = reviewer.prompt_for(
            node_id, self._context, self._developer_report,
            self._extra_context, self._retry_feedback, self._valid_targets,
        )
        try:
            self.client.send_message(reviewer.session_id, prompt, reviewer.agent)
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
        latest = self._latest_text(messages)
        if latest and self._parser_has_marker(latest):
            report = self._extract_report(latest)
            self._log("node_done", node=self._node, outcome="complete",
                      report_len=len(report or ""))
            self._developer_report = report
            if report is not None:
                self._env["report"] = report
            self._record_worklog(self._node, report)
            self._advance()
        self._report_to_constitution()

    def _step_judge(self) -> None:
        try:
            messages = self.client.read_messages(self._wait_sid)
        except Exception as exc:
            self._state = _ST_ERROR
            self._result = (Outcome.ERROR, self._node, str(exc))
            return
        text = self._latest_text(messages)
        if not text:
            self._report_to_constitution()
            return
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
        self._report_to_constitution()

    def _handle_verdict(self, result) -> None:
        verdict = result.verdict
        action = verdict.action
        self._log("reviewer_verdict", node=self._node, verdict=verdict.verdict,
                  action=action, confidence=verdict.confidence)
        if action == "advance":
            target = verdict.next_state
            if target in self._valid_targets:
                self._log("advance", to=target)
                self._phase = _PH_NONE
                self._advance(target)
                return
            self._state = _ST_ERROR
            self._result = (Outcome.ERROR, self._node, f"bad advance target '{target}'")
            return
        if action == "ask_developer":
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
            # route the rework back through the work role as an agent node
            work_sid = self.sessions.ensure("developer").session_id
            try:
                self.client.send_message(work_sid, inquiry.inquiry_text(),
                                         self.sessions.agent_for("developer"))
            except Exception as exc:
                self._state = _ST_ERROR
                self._result = (Outcome.ERROR, self._node, str(exc))
                return
            self._wait_sid = work_sid
            self._phase = _PH_AGENT
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
        if self._check_session_capacity(self.sessions.get(self._anchor), next_node):
            pass
        self._phase = _PH_NONE
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

    def _report_to_constitution(self) -> None:
        """Feed the alive session's state to the constitution as a REPORT."""
        if self.bus is None or self._wait_sid is None:
            return
        try:
            status = self.client.session_status(self._wait_sid)
            reasoning, output = self.client.session_tokens(self._wait_sid)
        except Exception:
            return
        latest_text = ""
        try:
            latest_text = self._latest_text(self.client.read_messages(self._wait_sid))
        except Exception:
            pass
        self.send("constitution", SignalKind.REPORT, {
            "session_id": self._wait_sid, "status": status,
            "output": output, "latest_text": latest_text,
        })

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
        marker = self.sm.regime.meta.work_done_marker
        ws = workspace_for(role_id or node.role)
        ws_hint = (
            f"\n工作区：你只在 {ws['work_dir']} 目录内工作变更，可读可见目录：{', '.join(ws['visible'])}，"
            f"可写目录：{', '.join(ws['writable'])}。"
        )
        return (
            f"【当前节点：{node_id}】{node.desc}\n"
            f"任务上下文：{context}\n"
            f"{ws_hint}\n"
            f"请完成本节点工作。每段结束时，最后一行以 {marker} 标记，"
            f"并在其前给出结构化汇报：改动文件 / 测试命令与结果 / 技术债 / 待决点。"
        )

    def _parser_has_marker(self, text) -> bool:
        return self.segment_parser.has_segment_end(text)

    def _extract_report(self, text) -> str | None:
        return self.segment_parser.extract_report(text)

    def _latest_text(self, messages) -> str:
        text = ""
        for m in reversed(messages):
            if getattr(m, "role", None) == "assistant" and getattr(m, "text", "").strip():
                text = m.text
                break
        return text

    def _record_worklog(self, node_id, report) -> None:
        if self.task_control is None:
            return
        self.task_control.init("worklog")
        self.task_control.append("worklog", f"节点 {node_id} 完成。\n{report or ''}")

    def _apply_transition(self, prev_node, next_node) -> None:
        try:
            prev_role = self.sm.node(prev_node).role
            policy = self.roles.get(prev_role).policy
            decision = policy.on_node_transition(prev_node, next_node, self._env)
            self._log("transition", from_node=prev_node, to_node=next_node,
                      role=prev_role, decision=decision.value)
            if decision == TransitionDecision.ROTATE:
                self.session_rotator.rotate_with_handover(
                    prev_role, summary=f"节点 {prev_node} 完成，流转到 {next_node}。",
                    handoff_kind="normal")
        except Exception:
            pass

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
        except Exception:
            pass
        return False

    def _log(self, event, **fields) -> None:
        if self.ledger is not None:
            self.ledger.append(event, **fields)