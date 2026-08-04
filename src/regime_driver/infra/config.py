"""Configuration loading (defaults < file < env < overrides)."""

from __future__ import annotations

import json
import os
import tomllib
from pathlib import Path

from .settings import Settings

_ENV_PREFIX = "REGIME_"


def load_settings(
    config_file: str | Path | None = None,
    overrides: dict | None = None,
) -> Settings:
    """Load settings from file, env, and explicit overrides (highest wins).

    Args:
        config_file: optional JSON or TOML file path.
        overrides: explicit dict of field->value (CLI args), highest precedence.
    """
    data: dict = {}

    # 1. config file
    if config_file:
        path = Path(config_file)
        if not path.exists():
            raise FileNotFoundError(f"config file not found: {path}")
        text = path.read_text(encoding="utf-8")
        if path.suffix == ".toml":
            data.update(tomllib.loads(text))
        elif path.suffix in (".json", ""):
            data.update(json.loads(text))
        else:
            raise ValueError(f"unsupported config format: {path.suffix}")

    # 2. env vars (REGIME_<FIELD>)
    for field in Settings.model_fields:
        env_name = _ENV_PREFIX + field.upper()
        if env_name in os.environ:
            data[field] = os.environ[env_name]

    # 3. explicit overrides (CLI)
    if overrides:
        data.update({k: v for k, v in overrides.items() if v is not None})

    return Settings.model_validate(data)