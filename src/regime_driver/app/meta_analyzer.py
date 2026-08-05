"""Meta-analysis (app layer): independent intelligent review of stalls.

This is the D1 architecture-gap fix: an independent LLM reviews the session's
recent messages with timestamps, cross-checking whether a stall detected by the
deterministic monitor (app/monitor.py) is a REAL problem or normal progress. It
uses its own ephemeral session (never the developer/reviewer session), so it is
independent of the monitored work.

The reviewer outputs a STRICT JSON verdict which passes through a deterministic
gate (mirroring DESIGN principles): only gated, valid verdicts drive escalation.
This is the "independent monitor that confirms timeout risk" the user asked for.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..core.json_utils import extract_json
from ..infra.opencode import Message, OpenCodeClient
from ..infra.settings import Settings

ALLOWED_VERDICTS = {"normal", "stalled", "looping", "blocked", "error", "escalate"}
ALLOWED_ACTIONS = {"none", "nudge", "abort", "fallback_model", "restart", "human"}
# destructive/heavy actions demand higher confidence
ACTION_CONF_MIN = {
    "none": 0.0,
    "nudge": 0.4,
    "abort": 0.5,
    "fallback_model": 0.5,
    "restart": 0.75,
    "human": 0.75,
}
VERDICT_ACTION_OK = {
    "normal": {"none", "nudge"},
    "stalled": {"abort", "fallback_model", "restart", "nudge"},
    "looping": {"abort", "fallback_model", "restart"},
    "blocked": {"nudge", "none", "human"},
    "error": {"fallback_model", "abort", "restart", "human"},
    "escalate": {"human", "fallback_model", "restart"},
}

META_SYSTEM = (
    "You are an independent monitor of an autonomous coding agent. You review "
    "whether the agent is making NORMAL progress or is stuck (stalled/looping/"
    "blocked). You are given the goal, time, deadline, session status, recent "
    "messages WITH timestamps, and recent monitor events. Return STRICT JSON only, "
    "no prose, matching exactly this schema:\n"
    '{"verdict":"normal|stalled|looping|blocked|error|escalate",'
    '"confidence":0.0,"recommended_action":"none|nudge|abort|fallback_model|restart|human",'
    '"reason":"1-2 sentences","evidence":"what the timestamps/messages show"}\n'
    "Rules: verdict normal only if recent messages show real progress (tool calls, "
    "output text, advancing timestamps). looping/stalled if busy but no output for "
    "a long time. confidence 0..1. recommended_action must be one of the listed values."
)


@dataclass
class MetaResult:
    """Outcome of one meta-analysis review."""

    verdict: str | None = None
    action: str | None = None
    confidence: float = 0.0
    reason: str = ""
    evidence: str = ""
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.verdict is not None and self.action is not None


class MetaAnalyzer:
    """Reviews a session's stall via an independent model + gate."""

    def __init__(self, settings: Settings, client: OpenCodeClient) -> None:
        self.settings = settings
        self.client = client

    def analyze(
        self,
        session_id: str,
        goal: str,
        deadline: str,
        messages: list[Message],
        recent_events: list[str],
    ) -> MetaResult:
        """Run one independent review of a session's recent activity."""
        context = self._build_context(messages, recent_events)
        prompt = (
            f"GOAL: {goal}\n"
            f"CURRENT_TIME: {_now()}  DEADLINE: {deadline}\n"
            f"SESSION_STATUS: (under review)\n"
            f"RECENT_MESSAGES (oldest->newest):\n{context}\n"
            f"RECENT_MONITOR_EVENTS:\n{'\n'.join(recent_events) or '(none)'}\n"
        )
        try:
            text = self.client.ask_and_get_text(
                session_id, META_SYSTEM + "\n\n" + prompt,
                self.settings.agent_reviewer,
                model=self.settings.meta_model,
            )
        except Exception as exc:
            return MetaResult(error=str(exc))
        return self._gate(text)

    def _build_context(self, messages: list[Message], recent_events: list[str]) -> str:
        lines = []
        for m in (messages or [])[-self.settings.meta_max_context_msgs:]:
            ts = m.ts or "?"
            text = re.sub(r"\s+", " ", m.text)[:200]
            lines.append(f"[{ts}] {m.role}: {text}")
        return "\n".join(lines) or "(no messages)"

    def _gate(self, text: str) -> MetaResult:
        raw = extract_json(text)
        if raw is None:
            return MetaResult(error="no JSON object in meta reply")
        verdict = str(raw.get("verdict", "")).strip().lower()
        action = str(raw.get("recommended_action", "")).strip().lower()
        try:
            conf = float(raw.get("confidence"))
        except (TypeError, ValueError):
            conf = -1.0
        reason = str(raw.get("reason", ""))[:300]
        evidence = str(raw.get("evidence", ""))[:300]

        if verdict not in ALLOWED_VERDICTS or action not in ALLOWED_ACTIONS:
            return MetaResult(error=f"verdict/action not allowed: {verdict}/{action}")
        if not (0.0 <= conf <= 1.0):
            return MetaResult(error=f"confidence out of bounds: {conf}")
        if conf < ACTION_CONF_MIN[action]:
            return MetaResult(error=f"confidence {conf} below min for {action}")
        if action not in VERDICT_ACTION_OK[verdict]:
            return MetaResult(error=f"verdict/action inconsistent: {verdict}/{action}")
        return MetaResult(verdict=verdict, action=action, confidence=conf,
                          reason=reason, evidence=evidence)


def _now() -> str:
    import datetime

    return datetime.datetime.now().isoformat(timespec="seconds")