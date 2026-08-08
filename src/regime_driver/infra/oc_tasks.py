"""Reader for the supervised-task registry (single derive, delegates to task).

Kept as a thin re-export so `regime report --tasks-dir` reads the registry
through one derive implementation (task.derive), never a second copy.
"""

from __future__ import annotations

from pathlib import Path

from ..task import TaskRegistry, derive  # noqa: F401  (derive re-exported for tests)


def load_tasks(tasks_dir: str | Path | None) -> list[dict]:
    """Load and normalize all supervised-task records (single derive)."""
    if not tasks_dir:
        return []
    return TaskRegistry(tasks_dir).list()
