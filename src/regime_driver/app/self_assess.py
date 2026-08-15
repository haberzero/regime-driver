"""Self-assessment (app layer): ask a session to evaluate its own state.

Per v3, a session is a "tiring person". The robot does NOT hard-decide capacity;
it asks the session to self-assess, returning a deterministic, parseable verdict
(CONTINUE / ROTATE / HANDOFF_NOW) plus its own estimate of remaining rounds.

The self-assessment runs in an independent ephemeral session (so it never
pollutes the session being evaluated). Parsing is strict; on an unparseable
reply the session is asked to retry, with an independent retry budget (not tied
to dialogue rounds).
"""

from __future__ import annotations

from ..core.json_utils import extract_json
from ..core.policy import RolePolicy, SelfAssessment
from ..core.session import SessionState
from ..infra.drive_client import DriveClient, OpenCodeError
from ..infra.settings import Settings


class SelfAssessor:
    """Runs a session's self-assessment with independent retry."""

    def __init__(
        self,
        settings: Settings,
        client: DriveClient,
        policy: RolePolicy,
        agent: str,
        max_retries: int = 2,
    ) -> None:
        self.settings = settings
        self.client = client
        self.policy = policy
        self.agent = agent
        self.max_retries = max_retries

    def assess(self, state: SessionState) -> SelfAssessment | None:
        """Ask the session to self-assess; returns a parsed assessment or None.

        Uses an ephemeral session so the evaluated session's context is untouched.
        Retries independently on unparseable replies.
        """
        meta_sid = None
        try:
            meta_sid = self.client.create_session("self-assess")
            usage = self._usage(state)
            prompt = self._build_prompt(state, usage)
            for _ in range(self.max_retries + 1):
                try:
                    text = self.client.ask_and_get_text(
                        meta_sid, self.policy.self_assess_system_prompt + "\n\n" + prompt,
                        self.agent, model=self.settings.model,
                    )
                except OpenCodeError:
                    break
                raw = extract_json(text)
                if raw is None:
                    continue  # unparseable -> retry
                try:
                    return SelfAssessment.from_dict(raw)
                except ValueError:
                    continue  # unparseable verdict -> retry
            return None
        finally:
            if meta_sid:
                try:
                    self.client.delete_session(meta_sid)
                except Exception:
                    pass

    def _usage(self, state: SessionState) -> float:
        # do not swallow a token-read failure into "0 usage" (that would silently
        # disable rotation and mask the fault); let it surface to the caller's
        # capacity check, which logs it.
        reasoning, output = self.client.session_tokens(state.session_id or "")
        total = reasoning + output
        limit = self.settings.context_limit_tokens
        return total / limit if limit else 0.0

    def _build_prompt(self, state: SessionState, usage: float) -> str:
        return (
            f"你正在评估自己的会话状态。当前是 {state.role} 会话。\n"
            f"上下文已使用约 {usage:.0%}。\n"
            f"请评估：是否应继续 / 旋转到新会话 / 立即交接。"
            f"同时估计你还能推进多少轮 (remaining_rounds_estimate)，"
            f"以及当前里程碑 (milestone_reachable) 是否可保存。"
        )