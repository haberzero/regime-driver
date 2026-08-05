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
    agent_developer: str = Field(default="developer", description="developer agent name")
    agent_reviewer: str = Field(default="reviewer", description="reviewer agent name")
    default_deadline_sec: int = Field(default=600, ge=1, description="per-segment deadline")
    poll_sec: float = Field(default=5.0, ge=0.1, description="session poll interval")
    ledger_path: str | None = Field(default=None, description="JSONL ledger path (None = off)")
    regime_path: str | None = Field(default=None, description="path to regime.json")
    session_turn_check: int = Field(default=5, ge=1, description="developer turn-check cadence")
    skills_dir: str | None = Field(default=None, description="path to workflow-regime skills dir")
    max_reviewer_retries: int = Field(default=2, ge=0, description="reviewer gate retries per node")
    max_dialogue_rounds: int = Field(
        default=5, ge=1,
        description="max reviewer/developer interrogation rounds per node (independent of gate retries)"
    )
    convergence_max_identical: int = Field(
        default=2, ge=2, description="same inquiry N+ times with no report change -> loop"
    )
    max_total_nodes: int = Field(
        default=50, ge=1, description="global cap on nodes executed per run (anti-runaway)"
    )
    task_control_dir: str | None = Field(
        default=None, description="project dir for task-control documents (None = off)"
    )
    # monitor thread (independent safety guard)
    monitor_enabled: bool = Field(default=True, description="enable the monitor thread")
    monitor_poll_sec: float = Field(default=3.0, ge=0.1, description="monitor poll interval")
    stall_sec: int = Field(default=120, ge=1, description="busy but no token growth beyond this -> stall")
    on_stall: Literal["abort", "report_user", "none"] = Field(
        default="abort", description="action when a session stalls (no progress)"
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
    log_level: Literal["debug", "info", "warning", "error"] = Field(default="info")