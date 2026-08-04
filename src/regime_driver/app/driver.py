"""RegimeDriver (app layer): the L1 fixed-code robot's main flow.

Instantiates the state machine, session manager, segment runner, and reviewer,
then advances a flow node by node. Developer nodes dispatch an instruction and
wait for [WORK_DONE]. Reviewer nodes invoke the L0 reviewer, gate the verdict,
and execute the verdict's action (ask_developer / advance / request_context /
abort_session / report_user). Hard rules (deadline, no-push) are enforced here.
No business rules live here; this is orchestration only.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.repetition import RepetitionDetector
from ..core.state_machine import StateMachine
from ..infra.ledger import Ledger
from ..infra.opencode import OpenCodeClient
from ..infra.settings import Settings
from ..infra.task_control import TaskControl
from .monitor import Monitor, MonitorEvent
from .reviewer import Reviewer
from .segment_runner import SegmentRunner
from .session_manager import SessionManager


@dataclass
class RunResult:
    """Result of a full flow run."""

    outcome: str  # "complete" | "error" | "timeout" | "blocked" | "human"
    end_node: str | None = None
    report: str | None = None
    detail: str | None = None


class RegimeDriver:
    """Main orchestrator: drive a flow on a developer session."""

    def __init__(
        self,
        settings: Settings,
        state_machine: StateMachine,
        client: OpenCodeClient,
        ledger: Ledger | None = None,
    ) -> None:
        self.settings = settings
        self.sm = state_machine
        self.client = client
        self.ledger = ledger
        self.sessions = SessionManager(
            client,
            developer_agent=settings.agent_developer,
            reviewer_agent=settings.agent_reviewer,
        )
        self.segments = SegmentRunner(client, poll_sec=settings.poll_sec)
        self.reviewer: Reviewer | None = None
        self.task_control: TaskControl | None = (
            TaskControl(settings.task_control_dir) if settings.task_control_dir else None
        )
        self.monitor: Monitor | None = None
        self._monitor_stop: str | None = None
        self._monitor_stop_end_node: str | None = None
        self._current_node: str | None = None
        self._cancel_event = lambda: self._monitor_stop is not None

    # -- helpers ------------------------------------------------------------

    def _log(self, event: str, **fields) -> None:
        if self.ledger is not None:
            self.ledger.append(event, **fields)

    def _current_node_set(self, node_id: str) -> None:
        self._current_node = node_id

    def _monitor_failure(self) -> RunResult | None:
        """Return a terminal RunResult if the monitor has flagged a stop."""
        if self._monitor_stop is not None:
            self._log("monitor_halt", kind=self._monitor_stop,
                      node=self._monitor_stop_end_node or self._current_node)
            return RunResult(
                outcome="blocked",
                end_node=self._monitor_stop_end_node or self._current_node,
                detail=f"monitor: {self._monitor_stop}",
            )
        return None

    def _get_reviewer(self) -> Reviewer:
        if self.reviewer is None:
            rev = self.sessions.ensure_reviewer()
            self.reviewer = Reviewer(
                client=self.client,
                session_id=rev.session_id,
                agent=self.sessions.reviewer_agent,
                state_machine=self.sm,
                skills_dir=self.settings.skills_dir,
                max_retries=self.settings.max_reviewer_retries,
            )
        return self.reviewer

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
        """
        self._log("monitor_event", kind=event.kind, session=event.session_id, detail=event.detail)
        if event.kind == "stall" and self.settings.on_stall == "none":
            return
        # escalate: set the stop flag FIRST (so any in-flight judge sees it), then abort
        self._monitor_stop = event.kind
        self._monitor_stop_end_node = self._current_node
        try:
            self.client.abort_session(event.session_id)
        except Exception as exc:
            self._log("monitor_abort_error", session=event.session_id, err=str(exc))

    def _build_instruction(self, node_id: str, context: str) -> str:
        node = self.sm.node(node_id)
        marker = self.sm.regime.meta.work_done_marker
        return (
            f"【当前节点：{node_id}】{node.desc}\n"
            f"任务上下文：{context}\n"
            f"请完成本节点工作。每段结束时，最后一行以 {marker} 标记，"
            f"并在其前给出结构化汇报：改动文件 / 测试命令与结果 / 技术债 / 待决点。"
        )

    # -- developer node -----------------------------------------------------

    def _run_developer_node(self, dev_sid: str, node_id: str, context: str) -> tuple[RunResult | None, str | None]:
        """Run a developer segment. Returns (failure, report) where failure is a
        terminal RunResult or None on success, and report is the [WORK_DONE] text."""
        instruction = self._build_instruction(node_id, context)
        result = self.segments.run(
            dev_sid,
            agent=self.sessions.developer_agent,
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
        if result.outcome != "complete":
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
        dev_sid: str,
        node_id: str,
        context: str,
        developer_report: str | None,
    ) -> tuple[RunResult | None, str | None, str | None]:
        """Run the reviewer judgement loop for a reviewer node.

        The reviewer call itself is retried internally (with feedback) in
        reviewer.judge. This loop handles the action loop:
          - ask_developer: send to developer, wait [WORK_DONE], feed report back
          - request_context: add extra context, re-judge
          - advance: return the reviewer-chosen next node
          - abort_session / report_user: terminate the run.

        The action loop is bounded by max_reviewer_retries to prevent a reviewer
        never converging on a forward action.

        Returns (failure, report, next_node) where failure is a terminal
        RunResult or None on success, report carries the latest developer report,
        and next_node is the reviewer-chosen advance target (or None).
        """
        reviewer = self._get_reviewer()
        valid_targets = set(self.sm.successors(node_id))
        extra_context: str | None = None
        for _ in range(self.settings.max_reviewer_retries + 1):
            self._log("reviewer_call", node=node_id)
            try:
                result = reviewer.judge(node_id, context, developer_report,
                                        extra_context, valid_targets, self._cancel_event)
            except Exception as exc:
                self._log("reviewer_error", node=node_id, err=str(exc))
                mf = self._monitor_failure()
                if mf:
                    return mf, None, None
                return RunResult(outcome="error", end_node=node_id, detail=str(exc)), None, None

            if not result.ok:
                self._log("reviewer_gate_exhausted", node=node_id,
                          reason=result.error or (result.gate.reason if result.gate else "?"))
                mf = self._monitor_failure()
                if mf:
                    return mf, None, None
                return RunResult(outcome="error", end_node=node_id,
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
                self._log("reviewer_bad_advance", node=node_id, next=target)
                return RunResult(outcome="error", end_node=node_id,
                                 detail=f"bad advance target '{target}'"), None, None
            if action == "ask_developer":
                msg = verdict.message_to_developer
                self._log("reviewer_ask_developer", node=node_id, msg=msg)
                failure, report = self._run_developer_node(dev_sid, node_id, msg or "")
                if failure is not None:
                    return failure, report, None
                developer_report = report
                continue  # feed new report back to reviewer
            if action == "request_context":
                extra_context = verdict.context_requested
                self._log("reviewer_request_context", node=node_id, req=extra_context)
                continue  # re-judge with more context
            if action == "abort_session":
                self.sessions.abort_developer()
                self._log("reviewer_abort", node=node_id, reason=verdict.reason)
                return RunResult(outcome="aborted", end_node=node_id, detail=verdict.reason), None, None
            if action == "report_user":
                self._log("reviewer_report_user", node=node_id, reason=verdict.reason)
                return RunResult(outcome="human", end_node=node_id, detail=verdict.reason), None, None

            self._log("reviewer_unknown_action", node=node_id, action=action)
            return RunResult(outcome="error", end_node=node_id,
                             detail=f"unknown action '{action}'"), None, None

        self._log("reviewer_action_loop_exhausted", node=node_id)
        return RunResult(outcome="error", end_node=node_id,
                         detail="reviewer action loop exhausted"), None, None

    # -- main flow ----------------------------------------------------------

    def run(self, context: str, title: str = "regime-driver") -> RunResult:
        """Run the whole flow on a fresh developer session and return the result."""
        self._log("flow_start", flow=self.sm.flow_name, context=context)
        self._current_node = None
        self._monitor_stop = None
        self._monitor_stop_end_node = None
        self._start_monitor()
        try:
            dev = self.sessions.ensure_developer(title)
            path = self.sm.flow_path()
            node_id = path[0]
            developer_report: str | None = None
            while node_id is not None:
                if self._monitor_stop is not None:
                    self._log("monitor_halt", kind=self._monitor_stop,
                              node=self._monitor_stop_end_node)
                    return RunResult(
                        outcome="blocked",
                        end_node=self._monitor_stop_end_node,
                        detail=f"monitor: {self._monitor_stop}",
                    )
                self._current_node = node_id
                self._log("node_enter", node=node_id, actor=self.sm.actor(node_id))
                actor = self.sm.actor(node_id)
                if actor == "developer":
                    failure, report = self._run_developer_node(dev.session_id, node_id, context)
                    if failure is not None:
                        return failure
                    developer_report = report
                    node_id = self.sm.next(node_id)
                elif actor == "reviewer":
                    failure, report, next_node = self._run_reviewer_node(
                        dev.session_id, node_id, context, developer_report
                    )
                    if failure is not None:
                        return failure
                    developer_report = report
                    node_id = next_node
                else:
                    # machine node: no external action (future)
                    node_id = self.sm.next(node_id)

                self.sessions.advance_developer_round()
                if self.sessions.developer_turn_check_due(self.settings.session_turn_check):
                    self._log("developer_turn_check", node=node_id,
                              round=self.sessions.developer.round)
            return RunResult(outcome="complete", end_node=path[-1] if path else None)
        except Exception as exc:
            self._log("flow_error", step="run", detail=str(exc))
            return RunResult(outcome="error", detail=str(exc))
        finally:
            self._stop_monitor()