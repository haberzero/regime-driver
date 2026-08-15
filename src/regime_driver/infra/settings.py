"""Runtime settings model (pydantic)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class Settings(BaseModel):
    """Configuration for the regime-driver run.

    Precedence (low->high): defaults < config file < env vars < CLI args.
    """

    base_url: str = Field(default="http://127.0.0.1:4097", description="worker opencode server URL")
    model: str = Field(default="deepseek-api/deepseek-v4-flash", description="model for all sessions")
    request_timeout: float = Field(
        default=600.0, ge=10.0,
        description="HTTP/stream timeout (s) for each message POST; slow judges may exceed the old 240s"
    )
    max_driver_wait_sec: float | None = Field(
        default=None, ge=60.0,
        description="driver.run() wait cap (s) when no explicit timeout/deadline is given; "
                    "None = no wall-clock cap (wait until terminal) — the SSE-liveness "
                    "watchdog and max_total_nodes remain the anti-runaway backstops"
    )
    agent_reviewer: str = Field(default="reviewer", description="reviewer agent name (for meta-analysis)")
    default_deadline_sec: int | None = Field(
        default=None, ge=1,
        description="per-phase wall-clock wait cap (s); None = disabled — a busy-but-"
                    "streaming phase must never be killed by wall clock, the SSE-liveness "
                    "watchdog is the stall backstop. Pass --deadline / set this to impose "
                    "an explicit kill switch."
    )
    poll_sec: float = Field(default=5.0, ge=0.1, description="session poll interval")
    human_confirm_timeout_sec: int = Field(
        default=300, ge=1,
        description="ask_human: how long the workflow waits for a dialog decision before the timeout default")
    human_default_on_timeout: Literal["block", "advance", "rework"] = Field(
        default="block",
        description="ask_human timeout default: 'block' | 'advance' (proceed to next node) | 'rework' (back to developer)")
    ledger_path: str | None = Field(default=None, description="JSONL ledger path (None = off)")
    regime_path: str | None = Field(default=None, description="path to regime.json")
    session_turn_check: int = Field(default=5, ge=1, description="[deprecated] dead config, no consumer")
    skills_dir: str | None = Field(default=None, description="path to workflow-regime skills dir")
    max_reviewer_retries: int = Field(default=3, ge=0, description="reviewer gate retries per node")
    max_dialogue_rounds: int = Field(
        default=5, ge=1,
        description="max reviewer/developer interrogation rounds per node (independent of gate retries)"
    )
    convergence_max_identical: int = Field(
        default=2, ge=2, description="same inquiry N+ times with no report change -> loop"
    )
    report_len_warn: int = Field(
        default=20000, ge=1,
        description="agent report length (chars) above which a report_len_warn audit event is logged"
    )
    max_total_nodes: int = Field(
        default=50, ge=1, description="global cap on nodes executed per run (anti-runaway)"
    )
    task_control_dir: str | None = Field(
        default=None, description="project dir for task-control documents (None = off)"
    )
    # mandatory permission ceiling: write ops are gated against THIS (config/env),
    # never against a self-declared CLI --perm. --perm can only lower, not raise.
    permission_ceiling: str = Field(
        default="clean", description="hard cap on write permission (read<interact<run<clean)"
    )
    # DEPRECATED: the watchdog is a runtime root invariant (I1), always on. No
    # consumer anywhere (preflight passes False but nothing reads it) — pure
    # compatibility retention.
    monitor_enabled: bool = Field(default=True, description="[deprecated] dead config, no consumer; watchdog is always on (I1)")
    monitor_poll_sec: float = Field(default=3.0, ge=0.1, description="[deprecated] no consumer; kept for compatibility")
    session_hygiene_threshold: int = Field(
        default=100, ge=1,
        description="doctor warns when accumulated worker sessions exceed this"
    )
    # Automatic session cleanup — a USER-CONFIGURABLE policy (reference model, not
    # enforced by default). Empty/None = disabled. Example value (JSON):
    #   {"max_sessions": 100, "min_age_sec": 3600, "only_idle": true}
    #   - max_sessions: 当 worker 累积 session 数超过此值时清理到该值以下
    #   - min_age_sec:  只清理存在超过该秒数的 session（0 = 不限）
    #   - only_idle:    true 只清理 idle 会话（默认 true，绝不删 busy）
    # 被 `regime sessions --cleanup` / doctor 提示 / supervisor 周期动作使用。
    session_cleanup_policy: str | None = Field(
        default=None,
        description="JSON session-cleanup policy (see docstring); None = disabled"
    )
    stall_sec: int = Field(default=180, ge=1, description="busy but no SSE-event-stream activity beyond this -> stall (liveness = SSE, not token counts; also the default policy kill threshold). 180s gives long-reasoning margin for providers that buffer output in bursts")
    on_stall: Literal["abort", "report_user", "none"] = Field(
        default="abort", description="[deprecated] dead config, no consumer; watchdog actions come from watchdog_policy_json"
    )
    # Programmable watchdog policy (optional). A JSON describing detection rules
    # + action ladder, e.g.:
    #   {"soft_sec": 30, "hard_sec": 600, "soft_action": "interrupt",
    #    "meta_gate_soft": true, "auto_resume_sec": 60}
    # Empty/None = the default policy (busy + no SSE activity > stall_sec -> kill).
    watchdog_policy_json: str | None = Field(
        default=None,
        description="JSON watchdog policy (rules/ladder/auto-resume); None = default",
    )
    auto_resume_sec: float = Field(
        default=30.0, ge=1.0,
        description="paused session auto-resumes after this many seconds",
    )
    # meta-analysis (independent intelligent review of stalls, D1)
    meta_analyze_enabled: bool = Field(
        default=False, description="confirm stalls with an independent model before acting"
    )
    meta_model: str = Field(
        default="deepseek-api/deepseek-v4-flash", description="model for independent stall review"
    )
    meta_max_context_msgs: int = Field(default=20, ge=1, description="messages fed to meta reviewer")
    # session lifecycle (brain-capacity management, policy-driven)
    context_limit_tokens: int = Field(
        default=120_000, ge=1000,
        description="session token ceiling; used to compute context usage fraction"
    )
    # context-budget handover policy (optional). A JSON describing when to
    # negotiate/hand a session over when its context window fills:
    #   {"enabled": true, "soft_fraction": 0.5, "hard_fraction": 0.7,
    #    "min_continue_nodes": 2, "handover_keep_messages": 30}
    # None = disabled (per-role RolePolicy thresholds apply instead).
    context_handover_policy_json: str | None = Field(
        default=None,
        description="JSON context-handover policy (soft/hard fractions, budget); None = disabled",
    )
    # runtime verification evidence: a judge node's `verify` shell command runs
    # on the HOST and its output is fed to the judge as independent runtime
    # evidence (e.g. pytest). Disabled in preflight/offline runs.
    worker_container: str = Field(
        default="opencode-worker", description="worker docker container name (used by verify/chaos/L4)")
    verify_enabled: bool = Field(
        default=False, description="run judge-node `verify` shell commands as runtime evidence (opt-in)")
    log_level: Literal["debug", "info", "warning", "error"] = Field(default="info")