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
    log_level: Literal["debug", "info", "warning", "error"] = Field(default="info")