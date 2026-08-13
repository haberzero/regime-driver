"""Reviewer interaction (app layer): invoke the reviewer and parse its reply.

The reviewer is a fixed-code-independent opencode session (read-only agent).
The robot assembles a prompt (node + skill + developer report + task context +
the explicit valid-node list), asks for a STRICT JSON verdict, parses it, and
runs it through the deterministic gate (core/contract). The gate is exact: no
fuzzy matching. A failed call is retried with the gate's rejection reason fed
back so the reviewer can correct itself. This is the ONLY channel between the driver
and the reviewer.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.contract import (
    ContractError,
    gate_reviewer_verdict,
    parse_reviewer_verdict,
)
from ..core.json_utils import extract_json
from ..core.models import GateResult, ReviewerVerdict
from ..core.state_machine import StateMachine
from ..infra.opencode import OpenCodeClient
from ..infra.skill_loader import load_skill

SYSTEM_PROMPT = (
    "You are the independent reviewer in an institutional-process robot. "
    "You are read-only: you cannot run commands or edit files. You judge the "
    "developer's work. Your ENTIRE reply must be EXACTLY ONE STRICT JSON OBJECT "
    "and NOTHING ELSE — no prose, no analysis, no commentary, no reasoning, no "
    "explanation, no markdown fences, no leading/trailing text. Do not mention "
    "your tools or capabilities. Output verbatim, matching exactly this schema:\n"
    "{\"node\":\"<node id>\",\"verdict\":\"issue_resolved|issue_pending|blocked|advance|human_escalate\","
    "\"action\":\"ask_developer|request_context|advance|abort_session|report_user\","
    "\"message_to_developer\":\"string|null\",\"next_state\":\"string|null\","
    "\"context_requested\":\"string|null\",\"confidence\":0.0,\"reason\":\"1-2 sentences\","
    "\"issues\":[{\"severity\":\"blocking|warning\",\"summary\":\"short\",\"detail\":\"optional|null\"}]}\n"
    "Rules:\n"
    "- Output the JSON object and stop. Do not add anything around it.\n"
    "- The prompt lists the VALID_NODES (id -> description). next_state must be "
    "EXACTLY one of those ids, verbatim (no paraphrase, no prefix, no translation).\n"
    "- advance requires next_state (a valid node id) and verdict issue_resolved/advance.\n"
    "- ask_developer requires a concrete message_to_developer instructing the developer.\n"
    "- request_context requires context_requested.\n"
    "- report_user is for blocked/human_escalate (needs human).\n"
    "- confidence 0..1; destructive actions (abort/report) need high confidence.\n"
    "- node must echo the node id given in the prompt.\n"
    "- issues: put EVERY real finding here, structured. severity=blocking means the "
    "work MUST NOT advance (correctness/security/contract violation); severity=warning "
    "means a documented non-blocking concern. If any blocking issue exists, action "
    "must NOT be advance — use ask_developer with a concrete message_to_developer so "
    "the developer fixes it and the gate then re-judges.\n"
    "Reply with ONLY the JSON object."
)


@dataclass
class ReviewerResult:
    """Outcome of one reviewer call."""

    verdict: ReviewerVerdict | None = None
    gate: GateResult | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.gate is not None and self.gate.ok and self.verdict is not None


@dataclass
class Reviewer:
    """Wraps the reviewer session and builds prompts for it."""

    client: OpenCodeClient
    session_id: str
    agent: str
    state_machine: StateMachine
    skills_dir: str | None = None
    max_retries: int = 2

    # -- prompt building ----------------------------------------------------

    def _valid_nodes_block(self, valid_targets: set[str]) -> str:
        lines = [f"- {nid}: {self.state_machine.node_descriptions()[nid]}" for nid in valid_targets]
        return "VALID_NODES (next_state must be exactly one id from this list):\n" + "\n".join(lines)

    def _build_prompt(
        self,
        node_id: str,
        context: str,
        developer_report: str | None,
        extra_context: str | None,
        retry_feedback: str | None,
        valid_targets: set[str],
    ) -> str:
        node = self.state_machine.node(node_id)
        skill_text = ""
        skill = node.skill
        if skill:
            # a node's required skill must be loadable; a missing skill is a config
            # error (guarded by mandatory preflight --deep) and must fail loudly,
            # not degrade the review with a placeholder.
            skill_text = load_skill(skill, self.skills_dir)

        parts = [
            f"当前节点：{node_id} — {node.desc}",
            self._valid_nodes_block(valid_targets),
            f"任务上下文：{context}",
        ]
        if extra_context:
            parts.append(f"补充上下文：\n{extra_context}")
        if developer_report:
            parts.append(f"开发者工作汇报：\n{developer_report}")
        if skill_text:
            parts.append(f"应用技能（{skill}）：\n{skill_text}")
        if retry_feedback:
            parts.append(f"你的上一次判定被确定性门拒绝，原因如下，请修正后重新输出：\n{retry_feedback}")
        parts.append("请按 SYSTEM 规则输出严格 JSON 判定对象。")
        return "\n\n".join(parts)

    # -- interaction --------------------------------------------------------

    def prompt_for(
        self,
        node_id: str,
        context: str,
        developer_report: str | None = None,
        extra_context: str | None = None,
        retry_feedback: str | None = None,
        valid_targets: set[str] | None = None,
    ) -> str:
        """Assemble the full reviewer prompt (SYSTEM + task) for a judge node.

        The workflow unit sends this prompt itself and then drives the reply
        polling, so a judge call never blocks the state machine thread.
        """
        if valid_targets is None:
            valid_targets = set(self.state_machine.successors(node_id))
        body = self._build_prompt(
            node_id, context, developer_report, extra_context, retry_feedback, valid_targets
        )
        return SYSTEM_PROMPT + "\n\n" + body

    def parse_reply(
        self,
        text: str,
        node_id: str,
        valid_targets: set[str] | None = None,
        extra_issues: list | None = None,
    ) -> ReviewerResult:
        """Parse + gate a reviewer's raw reply (workflow polls then calls this).

        `extra_issues`: programmatically-injected findings (e.g. a failed runtime
        verify) appended to the verdict BEFORE the gate runs — so a failure the
        reviewer might paper over still deterministically blocks advance (B3).
        """
        if valid_targets is None:
            valid_targets = set(self.state_machine.successors(node_id))
        return self._parse(text, node_id, valid_targets, extra_issues)

    def _parse(self, text: str, node_id: str, valid_targets: set[str] | None = None,
               extra_issues: list | None = None) -> ReviewerResult:
        raw = extract_json(text)
        if raw is None:
            return ReviewerResult(error="no JSON object in reviewer reply")
        try:
            verdict = parse_reviewer_verdict(raw)
        except ContractError as exc:
            return ReviewerResult(error=f"structural parse failed: {exc}")
        # node must be echoed back as provided
        if verdict.node != node_id:
            return ReviewerResult(error=f"node mismatch: got '{verdict.node}', expected '{node_id}'")
        if extra_issues:
            from ..core.models import ReviewerIssue
            coerced = [i if isinstance(i, ReviewerIssue) else ReviewerIssue.model_validate(i)
                       for i in extra_issues]
            verdict.issues = list(verdict.issues or []) + coerced
        gate = gate_reviewer_verdict(verdict, valid_targets)
        return ReviewerResult(verdict=verdict, gate=gate)