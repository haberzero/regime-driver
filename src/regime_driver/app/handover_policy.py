"""Context-budget handover policy (WORK_PLAN13) — the official template for
session-context-length management.

A session is a "tiring person": its context window fills up and quality
degrades. Rather than hard-cutting (which loses work) or silently continuing
(which degrades output), the robot negotiates with the session and hands off
with a REAL handover document when thresholds are reached.

Three modes, all configurable via `settings.context_handover_policy_json`:

  * below soft_fraction      : keep going, no interaction;
  * soft_fraction .. hard    : ask the session (ephemeral self-assess) for its
                               self-interrogation budget (remaining nodes) and
                               whether it may continue in the same session;
                               continue only with a sufficient budget, else rotate;
  * >= hard_fraction         : forced handover, no ask (context too full to
                               trust a self-assessment).

The handover document (交接格式) is built deterministically by the driver from
real session state (recent messages, current node, task context, last report),
so the new session has factual continuity even if the model's own summary is
unreliable. The new-session opening (交接提示词) wraps the document in an
instruction that keeps the workspace/contract unchanged.

This module is pure-ish (no network I/O); message content is passed in.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field


@dataclass
class ContextHandoverPolicy:
    """Configurable context-threshold + handover policy (from settings JSON)."""

    enabled: bool = True
    soft_fraction: float = 0.5          # >= this -> ask the session (negotiate)
    hard_fraction: float = 0.7          # >= this -> forced handover, no ask
    min_continue_nodes: int = 2         # consent needs at least this many nodes of budget
    handover_keep_messages: int = 30    # recent messages carried into the handover doc
    report_max_chars: int = 1200        # truncation for the last report in the doc
    document_template: str | None = None  # 阶段 2 (W-硬编码): custom `.format` doc template
    opening_template: str | None = None   # 阶段 2 (W-硬编码): custom `.format` opening template

    @classmethod
    def from_json(cls, raw: str | None) -> "ContextHandoverPolicy | None":
        """Parse a settings JSON string. None/empty disables the policy
        (falls back to per-role RolePolicy thresholds / legacy behaviour)."""
        if not raw:
            return None
        try:
            data = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ValueError(f"context_handover_policy_json is not valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ValueError("context_handover_policy_json must be a JSON object")
        enabled = bool(data.get("enabled", True))
        soft = float(data.get("soft_fraction", 0.5))
        hard = float(data.get("hard_fraction", 0.7))
        if not (0.0 < soft <= hard <= 1.0):
            raise ValueError(
                f"context_handover_policy fractions invalid: soft={soft} hard={hard} "
                "(need 0 < soft <= hard <= 1)")
        return cls(
            enabled=enabled,
            soft_fraction=soft,
            hard_fraction=hard,
            min_continue_nodes=max(1, int(data.get("min_continue_nodes", 2))),
            handover_keep_messages=max(1, int(data.get("handover_keep_messages", 30))),
            report_max_chars=max(100, int(data.get("report_max_chars", 1200))),
            document_template=data.get("document_template"),
            opening_template=data.get("opening_template"),
        )


def truncate(text: str, limit: int) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


def build_handover_document(
    *,
    role: str,
    node_id: str,
    node_desc: str,
    task_context: str,
    messages: list,
    last_report: str | None,
    keep: int = 30,
    report_max_chars: int = 1200,
    template: str | None = None,
) -> str:
    """The handover document (交接格式): a structured, self-contained summary
    a fresh session can act on without reading the old session's memory.

    `template` (阶段 2, W-硬编码) is an optional `.format`-style declarative
    template overriding the built-in shape. Available fields:
    `{role} {node_id} {node_desc} {task_context} {report} {messages}` (the
    recent-messages block is pre-rendered).
    """
    if template:
        return template.format(
            role=role, node_id=node_id, node_desc=node_desc,
            task_context=truncate(task_context, 300),
            report=truncate(last_report, report_max_chars) if last_report else "",
            messages=_render_messages(messages, keep),
        )
    lines = [
        f"# 会话交接文档（{role}）",
        f"- 任务：{truncate(task_context, 300)}",
        f"- 当前节点：{node_id} —— {node_desc}",
        f"- 交接模式：新会话接续，保持既有工作区产物与对外契约不变。",
    ]
    if last_report:
        lines.append(f"- 最近节点汇报：{truncate(last_report, report_max_chars)}")
    recent = list(messages or [])[-keep:]
    if recent:
        lines.append(f"- 最近会话记录（最后 {len(recent)} 条）：")
        for m in recent:
            who = getattr(m, "role", "?")
            body = truncate(getattr(m, "text", "") or "", 240)
            lines.append(f"  - [{who}] {body}")
    return "\n".join(lines)


def _render_messages(messages: list, keep: int) -> str:
    recent = list(messages or [])[-keep:]
    if not recent:
        return ""
    lines = [f"最近会话记录（最后 {len(recent)} 条）："]
    for m in recent:
        who = getattr(m, "role", "?")
        body = truncate(getattr(m, "text", "") or "", 240)
        lines.append(f"- [{who}] {body}")
    return "\n".join(lines)


def build_handover_opening(
    *,
    role: str,
    node_id: str,
    node_desc: str,
    task_context: str,
    document: str,
    usage: float,
    template: str | None = None,
) -> str:
    """The new-session opening message (交接提示词) for a fresh session.

    `template` (阶段 2, W-硬编码) is an optional `.format`-style declarative
    template overriding the built-in shape. Fields:
    `{role} {node_id} {node_desc} {task_context} {document} {usage}`.
    """
    usage_note = (
        f"上下文已用 {usage:.0%}" if usage > 0 else "会话上下文预算考量"
    )
    if template:
        return template.format(
            role=role, node_id=node_id, node_desc=node_desc,
            task_context=task_context, document=document, usage=usage_note,
        )
    return (
        f"【上下文交接】你是一个新会话，因{usage_note}而接续 {role} 会话，继续推进同一任务。\n"
        f"任务：{task_context}\n"
        f"你正处于节点：{node_id} —— {node_desc}\n"
        f"交接文档：\n{document}\n"
        "请基于交接文档继续完成当前节点的工作，保持既有工作区产物与对外契约不变。"
        "完成后仍按常规汇报格式汇报。"
    )


@dataclass
class HandoverDecision:
    """Result of the capacity negotiation for one session."""

    action: str            # "continue" | "rotate" | "handoff_now"
    usage: float
    reason: str = ""
    assessment_summary: str = ""
    forced: bool = False
