"""RegimeDriver (app layer): the L1 fixed-code robot's main flow.

Instantiates the state machine, session manager, segment runner, and reviewer,
then advances a flow node by node. Developer nodes dispatch an instruction and
wait for [WORK_DONE]. Reviewer nodes invoke the L0 reviewer, gate the verdict,
and execute the verdict's action (ask_developer / advance / request_context /
abort_session / report_user). Hard rules (deadline, no-push) are enforced here.
No business rules live here; this is orchestration only.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass

from ..core.handoff import Handoff, detect_loop
from ..core.models import NodeType, Outcome, SegmentOutcome
from ..core.policy import TransitionDecision
from ..core.role import RoleRegistry, default_roles
from ..core.state_machine import StateMachine
from ..infra.ledger import Ledger
from ..infra.opencode import OpenCodeClient
from ..infra.settings import Settings
from ..infra.task_control import TaskControl
from .meta_analyzer import MetaAnalyzer, MetaResult
from .monitor import Monitor, MonitorEvent
from .reviewer import Reviewer
from .segment_runner import SegmentRunner
from .session_lifecycle import SessionLifecycle, SessionRotator
from .session_manager import SessionRegistry


@dataclass
class RunResult:
    """Result of a full flow run."""

    outcome: Outcome
    end_node: str | None = None
    report: str | None = None
    detail: str | None = None


class RegimeDriver:
    """Main orchestrator: drive a flow on sessions (role-agnostic)."""

    def __init__(
        self,
        settings: Settings,
        state_machine: StateMachine,
        client: OpenCodeClient,
        ledger: Ledger | None = None,
        roles: RoleRegistry | None = None,
    ) -> None:
        self.settings = settings
        self.sm = state_machine
        self.client = client
        self.ledger = ledger
        self.roles = roles or default_roles()
        self.sessions = SessionRegistry(client, agent_by_role={
            rid: self.roles.get(rid).agent for rid in self.roles.ids()
        })
        self.segments = SegmentRunner(client, poll_sec=settings.poll_sec)
        self.reviewers: dict[str, Reviewer] = {}
        self.task_control: TaskControl | None = (
            TaskControl(settings.task_control_dir) if settings.task_control_dir else None
        )
        self.monitor: Monitor | None = None
        self._monitor_stop: str | None = None
        self._monitor_stop_end_node: str | None = None
        self._current_node: str | None = None
        self._cancel_event = threading.Event()
        self.meta_analyzer = MetaAnalyzer(settings, client)
        self._goal: str = ""
        self._deadline: str = ""
        self.session_lifecycle = SessionLifecycle(settings, client, self.roles)
        self.session_rotator = SessionRotator(client, self.sessions)

    # -- helpers ------------------------------------------------------------

    def _log(self, event: str, **fields) -> None:
        if self.ledger is not None:
            self.ledger.append(event, **fields)

    def _monitor_failure(self) -> RunResult | None:
        """Return a terminal RunResult if the monitor has flagged a stop."""
        if self._monitor_stop is not None:
            self._log("monitor_halt", kind=self._monitor_stop,
                      node=self._monitor_stop_end_node or self._current_node)
            return RunResult(
                outcome=Outcome.BLOCKED,
                end_node=self._monitor_stop_end_node or self._current_node,
                detail=f"monitor: {self._monitor_stop}",
            )
        return None

    def _get_reviewer(self, role_id: str) -> Reviewer:
        if role_id not in self.reviewers:
            rev = self.sessions.ensure(role_id)
            role = self.roles.get(role_id)
            self.reviewers[role_id] = Reviewer(
                client=self.client,
                session_id=rev.session_id,
                agent=role.agent,
                state_machine=self.sm,
                skills_dir=role.skills_dir or self.settings.skills_dir,
                max_retries=self.settings.max_reviewer_retries,
            )
        return self.reviewers[role_id]

    # -- safety monitor -----------------------------------------------------

    def _start_monitor(self) -> None:
        """Start the independent safety monitor thread (guards the whole run)."""
        if not self.settings.monitor_enabled or self.monitor is not None:
            return
        self.monitor = Monitor(
            settings=self.settings,
            client=self.client,
            session_provider=self.sessions.all_session_ids,
            handler=self._on_monitor_event,
        )
        self.monitor.start()

    def _stop_monitor(self) -> None:
        if self.monitor is not None:
            self.monitor.stop()
            self.monitor = None

    def _on_monitor_event(self, event: MonitorEvent) -> None:
        """Emergency stop handler: abort the affected session and flag the run.

        This is the authoritative "human pressed ESC" equivalent — it can
        interrupt a turn the main flow cannot detect on its own.

        If meta-analysis is enabled, a stall/dead_loop is first confirmed by an
        independent model before escalating (D1), so a false positive doesn't
        kill a healthy run.
        """
        self._log("monitor_event", kind=event.kind, session=event.session_id, detail=event.detail)
        if self.settings.on_stall == "none":
            return  # monitoring only; no action for stalls or dead-loops
        if self.settings.meta_analyze_enabled and event.kind in ("stall", "dead_loop"):
            self._dispatch_meta_review(event)
            return
        self._apply_monitor_action(event)

    def _apply_monitor_action(self, event: MonitorEvent) -> None:
        """Apply the configured on_stall action to a monitor event (no meta path)."""
        if self.settings.on_stall == "report_user":
            self._report_monitor_blocked(event)
            return
        self._escalate_monitor(event)

    def _escalate_monitor(self, event: MonitorEvent) -> None:
        """Set the stop flag FIRST (so any in-flight judge sees it), then abort."""
        self._monitor_stop = event.kind
        self._monitor_stop_end_node = self._current_node
        self._cancel_event.set()
        try:
            self.client.abort_session(event.session_id)
        except Exception as exc:
            self._log("monitor_abort_error", session=event.session_id, err=str(exc))

    def _dispatch_meta_review(self, event: MonitorEvent) -> None:
        """Confirm a stall with an independent model in a background thread."""
        def worker() -> None:
            meta_sid = None
            try:
                meta_sid = self.client.create_session("meta-review")
                messages = self.client.read_messages(event.session_id)
                result: MetaResult = self.meta_analyzer.analyze(
                    meta_sid, goal=self._goal or "", deadline=self._deadline or "",
                    messages=messages, recent_events=[],
                )
                self._log("meta_review", kind=event.kind, session=event.session_id,
                          verdict=result.verdict, action=result.action,
                          confidence=result.confidence,
                          error=result.error, reason=result.reason)
                if result.ok:
                    self._apply_meta_result(event, result)
                else:
                    # meta review failed; fall back to deterministic handling
                    self._log("meta_review_fallback", kind=event.kind, session=event.session_id)
                    self._escalate_monitor(event)
            except Exception as exc:
                self._log("meta_review_error", session=event.session_id, err=str(exc))
            finally:
                if meta_sid:
                    try:
                        self.client.delete_session(meta_sid)
                    except Exception:
                        pass
        threading.Thread(target=worker, daemon=True).start()

    def _apply_meta_result(self, event: MonitorEvent, result: MetaResult) -> None:
        """Honor the meta reviewer's verdict + recommended_action.

        - verdict "normal": false positive, do nothing.
        - action "none": do nothing (reviewer says leave it).
        - action "nudge": light touch — if on_stall is report_user, just report;
          else abort (stop the run) since a stuck turn is not recoverable here.
        - action abort/restart/human: escalate (stop + abort).
        - on_stall "report_user": report without aborting.
        """
        if result.verdict == "normal" or result.action == "none":
            self._log("meta_review_clear", kind=event.kind, session=event.session_id,
                      verdict=result.verdict)
            return
        if self.settings.on_stall == "report_user":
            self._log("meta_review_report", kind=event.kind, session=event.session_id,
                      verdict=result.verdict, action=result.action)
            self._report_monitor_blocked(event, result)
            return
        # escalate (abort + stop) for any confirmed non-normal variant
        self._escalate_monitor(event)

    def _report_monitor_blocked(self, event: MonitorEvent, result: MetaResult | None = None) -> None:
        """Report a blocked run to the human without aborting the session."""
        self._monitor_stop = event.kind
        self._monitor_stop_end_node = self._current_node
        self._cancel_event.set()

    def _build_instruction(self, node_id: str, context: str) -> str:
        node = self.sm.node(node_id)
        marker = self.sm.regime.meta.work_done_marker
        return (
            f"【当前节点：{node_id}】{node.desc}\n"
            f"任务上下文：{context}\n"
            f"请完成本节点工作。每段结束时，最后一行以 {marker} 标记，"
            f"并在其前给出结构化汇报：改动文件 / 测试命令与结果 / 技术债 / 待决点。"
        )

    # -- agent node (developer-style work) ----------------------------------

    def _run_agent_node(self, sid: str, role_id: str, node_id: str, context: str) -> tuple[RunResult | None, str | None]:
        """Run an agent segment. Returns (failure, report)."""
        instruction = self._build_instruction(node_id, context)
        result = self.segments.run(
            sid,
            agent=self.sessions.agent_for(role_id),
            instruction=instruction,
            deadline_sec=self.settings.default_deadline_sec,
            cancel_event=self._cancel_event,
        )
        self._log(
            "node_done",
            node=node_id,
            outcome=result.outcome,
            report_len=len(result.report or ""),
        )
        if result.outcome != SegmentOutcome.COMPLETE:
            mf = self._monitor_failure()
            if mf:
                return mf, None
            return RunResult(
                outcome=result.outcome,
                end_node=node_id,
                report=result.report,
                detail=result.detail,
            ), None
        self._record_worklog(node_id, result.report)
        return None, result.report

    def _record_worklog(self, node_id: str, report: str | None) -> None:
        """Persist a node completion to the task-control WORKLOG (if enabled)."""
        if self.task_control is None:
            return
        self.task_control.init("worklog")
        entry = f"节点 {node_id} 完成。\n{report or ''}"
        self.task_control.append("worklog", entry)

    # -- reviewer node (judgement loop) -------------------------------------

    def _run_reviewer_node(
        self,
        work_sid: str,
        judge_role: str,
        work_role: str,
        node_id: str,
        context: str,
        developer_report: str | None,
    ) -> tuple[RunResult | None, str | None, str | None]:
        """Run the judgement loop for a judge-type node.

        v2: roles collaborate via structured handoffs, not manual text relay.
        The judging role produces inquiry handoffs; the working role returns
        report handoffs; the judge consumes ONLY the report (never the working
        role's session memory). Bounded by max_dialogue_rounds + convergence.
        """
        reviewer = self._get_reviewer(judge_role)
        valid_targets = set(self.sm.successors(node_id))
        extra_context: str | None = None
        rounds: list[tuple[str, str]] = []  # (inquiry_text, report_text) history
        for _ in range(self.settings.max_dialogue_rounds):
            self._log("reviewer_call", node=node_id)
            try:
                result = reviewer.judge(node_id, context, developer_report,
                                        extra_context, valid_targets, self._cancel_event)
            except Exception as exc:
                self._log("reviewer_error", node=node_id, err=str(exc))
                mf = self._monitor_failure()
                if mf:
                    return mf, None, None
                return RunResult(outcome=Outcome.ERROR, end_node=node_id, detail=str(exc)), None, None

            if not result.ok:
                self._log("reviewer_gate_exhausted", node=node_id,
                          reason=result.error or (result.gate.reason if result.gate else "?"))
                mf = self._monitor_failure()
                if mf:
                    return mf, None, None
                return RunResult(outcome=Outcome.ERROR, end_node=node_id,
                                 detail="reviewer gate exhausted"), None, None

            verdict = result.verdict
            action = verdict.action
            self._log("reviewer_verdict", node=node_id, verdict=verdict.verdict,
                      action=action, confidence=verdict.confidence)

            if action == "advance":
                target = verdict.next_state
                if target in valid_targets:
                    self._log("advance", to=target)
                    return None, developer_report, target
                return RunResult(outcome=Outcome.ERROR, end_node=node_id,
                                 detail=f"bad advance target '{target}'"), None, None
            if action == "ask_developer":
                # reviewer -> developer inquiry handoff
                inquiry = Handoff.reviewer_inquiry(
                    criticisms=[verdict.reason] if verdict.reason else [],
                    required_rework=verdict.message_to_developer or "",
                    flow_node=node_id,
                )
                self._log("reviewer_inquiry", node=node_id, msg=inquiry.summary)
                failure, report = self._run_agent_node(work_sid, work_role, node_id, inquiry.inquiry_text())
                if failure is not None:
                    return failure, report, None
                developer_report = report
                # record this interrogation round for convergence detection
                rounds.append((inquiry.inquiry_text(), report or ""))
                if detect_loop(rounds, self.settings.convergence_max_identical):
                    self._log("reviewer_loop_detected", node=node_id)
                    return RunResult(outcome=Outcome.BLOCKED, end_node=node_id,
                                     detail="reviewer/developer interrogation is looping"), None, None
                continue  # feed report back to reviewer
            if action == "request_context":
                extra_context = verdict.context_requested
                self._log("reviewer_request_context", node=node_id, req=extra_context)
                continue
            if action == "abort_session":
                self.sessions.abort(work_role)
                return RunResult(outcome=Outcome.ABORTED, end_node=node_id, detail=verdict.reason), None, None
            if action == "report_user":
                return RunResult(outcome=Outcome.HUMAN, end_node=node_id, detail=verdict.reason), None, None

            self._log("reviewer_unknown_action", node=node_id, action=action)
            return RunResult(outcome=Outcome.ERROR, end_node=node_id,
                             detail=f"unknown action '{action}'"), None, None

        self._log("reviewer_dialogue_exhausted", node=node_id)
        return RunResult(outcome=Outcome.ERROR, end_node=node_id,
                         detail="reviewer dialogue rounds exhausted"), None, None

    # -- main flow ----------------------------------------------------------

    def _check_session_capacity(self, dev, node_id: str) -> bool:
        """Drive brain-capacity rotation via self-assessment + policy.

        Returns True if the session was rotated (caller should refresh `dev`).
        """
        try:
            if not self.session_lifecycle.should_self_assess(dev):
                return False
            usage = round(self.session_lifecycle.capacity_used(dev), 2)
            # if already urgent, skip self-assessment (decide forces handoff)
            assessment = None
            if not self.session_lifecycle.policy_for(dev.role).is_urgent(usage):
                assessment = self.session_lifecycle.assess(dev, usage)
            action = self.session_lifecycle.decide(dev, assessment, usage)
            self._log("session_capacity_check", node=node_id, session=dev.session_id,
                      used=usage, action=action,
                      verdict=assessment.verdict if assessment else None,
                      remaining=assessment.remaining_rounds_estimate if assessment else None)
            if action == "handoff_now":
                summary = (f"紧急：上下文已用 {usage:.0%}。当前流程节点 {node_id}。"
                           f"任务上下文：{self._goal[:100]}")
                self.session_rotator.rotate_with_handover(
                    dev.role, summary=summary,
                    constraints=["禁 push"], handoff_kind="urgent",
                )
                self._log("session_rotated", node=node_id, reason="urgent",
                          new_session=self.sessions.get(dev.role).session_id)
                return True
            if action == "rotate":
                summary = (f"当前流程节点 {node_id}。上下文已用 {usage:.0%}，"
                           f"里程碑可保存，切换会话。任务上下文：{self._goal[:100]}")
                self.session_rotator.rotate_with_handover(
                    dev.role, summary=summary,
                    constraints=["禁 push"], handoff_kind="normal",
                )
                self._log("session_rotated", node=node_id, reason="rotate",
                          new_session=self.sessions.get(dev.role).session_id)
                return True
            # action == "continue"
            return False
        except Exception as exc:
            self._log("session_capacity_error", node=node_id, err=str(exc))
            return False

    def _execute_node(
        self,
        node_id: str,
        context: str,
        developer_report: str | None,
        work_role: str,
    ) -> tuple[RunResult | None, str | None, str | None]:
        """Execute a single node by its type; return (failure, report, next_node).

        A node is dispatched by its `type` (what it does), independent of which
        role owns it. agent=work, judge=judgement, tool=deterministic, etc.
        """
        node = self.sm.node(node_id)
        ntype = node.type
        role = node.role
        self._log("node_enter", node=node_id, type=ntype.value, role=role)

        if ntype == NodeType.AGENT:
            sid = self.sessions.ensure(role).session_id
            failure, report = self._run_agent_node(sid, role, node_id, context)
            if failure is not None:
                return failure, None, None
            return None, report, self.sm.next(node_id)

        if ntype == NodeType.JUDGE:
            # judging role = this node's role; work role = the working role
            # (defaults to developer, the stable anchor)
            judge_role = role
            work_rid = work_role or "developer"
            work_sid = self.sessions.ensure(work_rid).session_id
            failure, report, next_node = self._run_reviewer_node(
                work_sid, judge_role, work_rid, node_id, context, developer_report
            )
            if failure is not None:
                return failure, None, None
            return None, report, next_node

        # tool / route / gate: reserved (fall through to next for now)
        return None, None, self.sm.next(node_id)

    def _apply_transition(self, prev_node: str, next_node: str) -> None:
        """Handle a node transition per the prev node's role policy.

        The role's RolePolicy.on_node_transition decides whether the role's
        session is reused, rotated, or pinned as an anchor when the flow advances.
        """
        try:
            prev_role = self.sm.node(prev_node).role
            policy = self.roles.get(prev_role).policy
            decision = policy.on_node_transition(prev_node, next_node)
            self._log("transition", from_node=prev_node, to_node=next_node,
                      role=prev_role, decision=decision.value)
            if decision == TransitionDecision.ROTATE:
                summary = (f"节点 {prev_node} 完成，流转到 {next_node}。"
                           f"角色 {prev_role} 会话交接换新。任务上下文：{self._goal[:100]}")
                self.session_rotator.rotate_with_handover(
                    prev_role, summary=summary, handoff_kind="normal",
                )
                self._log("transition_rotated", role=prev_role,
                          new_session=self.sessions.get(prev_role).session_id)
        except Exception as exc:
            self._log("transition_error", from_node=prev_node, to_node=next_node,
                      err=str(exc))

    def _anchor_role(self) -> str:
        """The primary working role for this flow (first agent node's role).

        The kernel is role-agnostic; the anchor is whoever does the primary work.
        Falls back to "developer" if no agent node is found.
        """
        for nid in self.sm.flow_path():
            node = self.sm.node(nid)
            if node.type == NodeType.AGENT:
                return node.role
        return "developer"

    def run(self, context: str, title: str = "regime-driver") -> RunResult:
        """Run the whole flow on a fresh developer session and return the result."""
        self._log("flow_start", flow=self.sm.flow_name, context=context)
        self._current_node = None
        self._monitor_stop = None
        self._monitor_stop_end_node = None
        self._cancel_event.clear()
        self._goal = context
        self._deadline = ""  # set by caller if a deadline is configured
        self._start_monitor()
        try:
            anchor = self._anchor_role()
            dev = self.sessions.ensure(anchor, title)
            path = self.sm.flow_path()
            node_id = path[0]
            developer_report: str | None = None
            node_count = 0
            while node_id is not None:
                node_count += 1
                if node_count > self.settings.max_total_nodes:
                    self._log("flow_node_budget_exhausted", node=node_id)
                    return RunResult(outcome=Outcome.BLOCKED, end_node=node_id,
                                     detail=f"exceeded max_total_nodes ({self.settings.max_total_nodes})")
                mf = self._monitor_failure()
                if mf:
                    return mf
                self._current_node = node_id
                failure, report, next_node = self._execute_node(
                    node_id, context, developer_report, anchor
                )
                if failure is not None:
                    return failure
                developer_report = report
                if next_node is not None:
                    self._apply_transition(node_id, next_node)
                node_id = next_node

                self.sessions.advance_round(anchor)
                if self.sessions.turn_check_due(anchor, self.settings.session_turn_check):
                    self._log("developer_turn_check", node=node_id,
                              round=self.sessions.get(anchor).round)
                if self._check_session_capacity(dev, node_id):
                    dev = self.sessions.get(anchor)  # refresh after rotation
            return RunResult(outcome=Outcome.COMPLETE, end_node=path[-1] if path else None)
        except Exception as exc:
            self._log("flow_error", step="run", detail=str(exc))
            return RunResult(outcome=Outcome.ERROR, detail=str(exc))
        finally:
            self._stop_monitor()