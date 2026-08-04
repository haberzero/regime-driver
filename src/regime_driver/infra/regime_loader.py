"""Regime descriptor loading (infra: file I/O lives here, not in core).

Reads a regime.json file and builds a StateMachine. Pure core/state_machine is
kept free of I/O; this module owns the file access and the default-path
resolution.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..core.state_machine import StateMachine, StateMachineError

# Default regime descriptor shipped inside the package (infra-owned, not core).
DEFAULT_REGIME = Path(__file__).parent.parent / "data" / "regime.json"


def load_regime(path: str | Path | None = None) -> StateMachine:
    """Load a StateMachine from a regime.json path.

    If path is None, falls back to the packaged default regime descriptor.
    """
    target = Path(path) if path else DEFAULT_REGIME
    if not target.exists():
        raise FileNotFoundError(f"regime file not found: {target}")
    try:
        raw = target.read_text(encoding="utf-8")
        return StateMachine.from_dict(raw)
    except json.JSONDecodeError as exc:
        raise StateMachineError(f"invalid JSON in {target}: {exc}") from exc