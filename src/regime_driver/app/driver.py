"""RegimeDriver (app layer): the L1 fixed-code robot's main flow.

Instantiates the state machine, session manager, and segment runner, then
advances a flow node by node: developer nodes dispatch an instruction and wait
for [WORK_DONE]; reviewer nodes are an extension point for M-3 (the real
reviewer + deterministic gate). No business rules live here; this is
orchestration only.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.state_machine import StateMachine
from ..infra.ledger import Ledger
from ..infra.opencode import OpenCodeClient
from ..infra.settings import Settings
from .segment_runner import SegmentRunner
from .session_manager import SessionManager


@dataclass
class RunResult:
    """Result of a full flow run."""

    outcome: str  # "complete" | "error" | "timeout"
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

    # -- helpers ------------------------------------------------------------

    def _log(self, event: str, **fields) -> None:
        if self.ledger is not None:
            self.ledger.append(event, **fields)

    def _build_instruction(self, node_id: str, context: str) -> str:
        node = self.sm.node(node_id)
        marker = self.sm.regime.meta.work_done_marker
        return (
            f"【当前节点：{node_id}】{node.desc}\n"
            f"任务上下文：{context}\n"
            f"请完成本节点工作。每段结束时，最后一行以 {marker} 标记，"
            f"并在其前给出结构化汇报：改动文件 / 测试命令与结果 / 技术债 / 待决点。"
        )

    # -- main flow ----------------------------------------------------------

    def run(self, context: str, title: str = "regime-driver") -> RunResult:
        """Run the whole flow on a fresh developer session and return the result.

        M-2 scope: drives developer nodes to [WORK_DONE]; reviewer nodes are
        passed through (M-3 will wire the real reviewer + gate). Every node
        advance bumps the developer round counter; at the configured cadence a
        session-turn check is recorded (full rotation/abort handling is M-3+).
        """
        self._log("flow_start", flow=self.sm.flow_name, context=context)
        try:
            dev = self.sessions.ensure_developer(title)
            path = self.sm.flow_path()
            for node_id in path:
                self._log("node_enter", node=node_id, actor=self.sm.actor(node_id))
                if self.sm.actor(node_id) == "developer":
                    instruction = self._build_instruction(node_id, context)
                    result = self.segments.run(
                        dev.session_id,
                        agent=self.sessions.developer_agent,
                        instruction=instruction,
                        deadline_sec=self.settings.default_deadline_sec,
                    )
                    self._log(
                        "node_done",
                        node=node_id,
                        outcome=result.outcome,
                        report_len=len(result.report or ""),
                    )
                    if result.outcome != "complete":
                        return RunResult(
                            outcome=result.outcome,
                            end_node=node_id,
                            report=result.report,
                            detail=result.detail,
                        )
                else:
                    # reviewer node: M-3 extension point (real reviewer + gate).
                    self._log("node_reviewer_pending", node=node_id)

                # advance round counter and record the periodic turn check
                self.sessions.advance_developer_round()
                if self.sessions.developer_turn_check_due(self.settings.session_turn_check):
                    self._log(
                        "developer_turn_check",
                        node=node_id,
                        round=self.sessions.developer.round,
                    )
            return RunResult(outcome="complete", end_node=path[-1] if path else None)
        except Exception as exc:
            self._log("flow_error", step="run", detail=str(exc))
            return RunResult(outcome="error", detail=str(exc))