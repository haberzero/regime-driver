"""Process-liveness helpers shared by the job registry and task registry.

Both ``infra/jobs.py`` (async ``regime run --async``) and ``task.py``
(supervised ``regime drive --async``) need to decide whether a tracked
background PID is still alive. The naive ``os.kill(pid, 0)`` probe returns True
for a **zombie** process (it still has a kernel entry awaiting reap), which makes
a crashed background job look permanently "running". This module provides a
single robust implementation that reads the process state from ``/proc`` and
treats zombies (state ``Z``) as dead.
"""

from __future__ import annotations

import os
from typing import Optional


def _pid_state(pid: int) -> Optional[str]:
    """Return the one-letter process state from ``/proc/<pid>/stat``.

    Returns ``None`` when the pid no longer exists or the stat file cannot be
    read. Parsing is careful: the comm field (field 2) may contain spaces and
    parentheses, so the state (field 3) is read as the token following the last
    ``)``.
    """
    try:
        with open(f"/proc/{int(pid)}/stat", encoding="utf-8") as fh:
            data = fh.read()
    except (OSError, ValueError):
        return None
    idx = data.rfind(")")
    if idx < 0:
        return None
    rest = data[idx + 2:].split()
    return rest[0] if rest else None


def pid_alive(pid) -> bool:
    """Return True only for a live, non-zombie process.

    A zombie (state ``Z``) or a nonexistent pid is considered dead. Falls back to
    ``os.kill(pid, 0)`` (as a pure existence probe) only on platforms without
    ``/proc`` (non-Linux), where zombies cannot be distinguished anyway.
    """
    if not pid:
        return False
    try:
        state = _pid_state(pid)
    except (ValueError, TypeError):
        return False
    if state is not None:
        # 'Z' = zombie, 'X' = dying/reaping: both should be considered dead
        return state not in ("Z", "X")
    # no /proc (non-Linux): fall back to the existence probe
    try:
        os.kill(int(pid), 0)
        return True
    except (PermissionError, ProcessLookupError, OSError, ValueError, TypeError):
        return False
