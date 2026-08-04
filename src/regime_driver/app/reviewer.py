"""Reviewer interaction (app layer): invoke the L0 reviewer and parse its reply.

The reviewer is a fixed-code-independent opencode session (read-only agent).
The L1 robot assembles a prompt (node + skill + developer report + task context +
the explicit valid-node list), asks for a STRICT JSON verdict, parses it, and
runs it through the deterministic gate (core/contract). The gate is exact: no
fuzzy matching. A failed call is retried with the gate's rejection reason fed
back so the reviewer can correct itself. This is the ONLY channel between L1
and L0.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from ..core.contract import (
    ContractError,
    gate_reviewer_verdict,
    parse_reviewer_verdict,
)
from ..core.models import GateResult, ReviewerVerdict
from ..core.state_machine import StateMachine
from ..infra.opencode import OpenCodeClient, OpenCodeError
from ..infra.skill_loader import SkillNotFoundError, load_skill

SYSTEM_PROMPT = (
    "You are the independent reviewer (L0) in an institutional-process robot. "
    "You are read-only: you cannot run commands or edit files. You judge the "
    "developer's work and output a STRICT JSON object, no prose, exactly matching "
    "this schema:\n"
    '{"node":"<node id>","verdict":"issue_resolved|issue_pending|blocked|advance|human_escalate",'
    '"action":"ask_developer|request_context|advance|abort_session|report_user",'
    '"message_to_developer":"string|null","next_state":"string|null",'
    '"context_requested":"string|null","confidence":0.0,"reason":"1-2 sentences"}\n'
    "Rules:\n"
    "- The prompt lists the VALID_NODES (id -> description). next_state must be "
    "EXACTLY one of those ids, verbatim (no paraphrase, no prefix, no translation).\n"
    "- advance requires next_state (a valid node id) and verdict issue_resolved/advance.\n"
    "- ask_developer requires a concrete message_to_developer instructing the developer.\n"
    "- request_context requires context_requested.\n"
    "- report_user is for blocked/human_escalate (needs human).\n"
    "- confidence 0..1; destructive actions (abort/report) need high confidence.\n"
    "- node must echo the node id given in the prompt.\n"
    "Return only the JSON object."
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

    def _valid_nodes_block(self, valid_targets: set[str] | None = None) -> str:
        targets = valid_targets or set(self.state_machine.successors(self.state_machine.start))
        lines = [f"- {nid}: {self.state_machine.node_descriptions()[nid]}" for nid in targets]
        return "VALID_NODES (next_state must be exactly one id from this list):\n" + "\n".join(lines)

    def _build_prompt(
        self,
        node_id: str,
        context: str,
        developer_report: str | None,
        extra_context: str | None,
        retry_feedback: str | None,
        valid_targets: set[str] | None = None,
    ) -> str:
        node = self.state_machine.node(node_id)
        skill_text = ""
        skill = node.skill
        if skill:
            try:
                skill_text = load_skill(skill, self.skills_dir)
            except SkillNotFoundError as exc:
                skill_text = f"(skill {skill} unavailable: {exc})"

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

    def judge(
        self,
        node_id: str,
        context: str,
        developer_report: str | None = None,
        extra_context: str | None = None,
        valid_targets: set[str] | None = None,
    ) -> ReviewerResult:
        """Call the reviewer, parse + gate the reply, retrying with feedback.

        valid_targets: the set of node ids the reviewer may advance to (the
        current node's successors). If None, defaults to the current node's
        successors (never the full node set, to prevent backward/self advance).

        Returns the first gated verdict, or a ReviewerResult carrying the last
        error/rejection reason.
        """
        if valid_targets is None:
            valid_targets = set(self.state_machine.successors(node_id))
        retry_feedback: str | None = None
        last_failure: ReviewerResult | None = None
        for attempt in range(self.max_retries + 1):
            prompt = self._build_prompt(
                node_id, context, developer_report, extra_context, retry_feedback, valid_targets
            )
            try:
                text = self.client.ask_and_get_text(
                    self.session_id, SYSTEM_PROMPT + "\n\n" + prompt, self.agent
                )
            except OpenCodeError as exc:
                last_failure = ReviewerResult(error=str(exc))
                break
            result = self._parse(text, node_id, valid_targets)
            if result.ok:
                return result
            last_failure = result
            retry_feedback = result.error or (result.gate.reason if result.gate else "unknown")
        return last_failure or ReviewerResult(error="reviewer failed")

    def _parse(self, text: str, node_id: str, valid_targets: set[str] | None = None) -> ReviewerResult:
        raw = _extract_json(text)
        if raw is None:
            return ReviewerResult(error="no JSON object in reviewer reply")
        try:
            verdict = parse_reviewer_verdict(raw)
        except ContractError as exc:
            return ReviewerResult(error=f"structural parse failed: {exc}")
        # node must be echoed back as provided
        if verdict.node != node_id:
            return ReviewerResult(error=f"node mismatch: got '{verdict.node}', expected '{node_id}'")
        gate = gate_reviewer_verdict(verdict, valid_targets)
        return ReviewerResult(verdict=verdict, gate=gate)


def _extract_json(text: str) -> dict | None:
    """Extract the first JSON object from a reply (handles fenced blocks)."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text)
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except json.JSONDecodeError:
        return None