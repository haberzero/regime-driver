"""Task-control document read/write (infra: file I/O).

Provides a thin, safe interface over the workflow-regime task-control documents
(NEXT_STEPS, WORKLOG, PENDING_TASKS). The robot reads them to build reviewer
context and updates them to record progress. The developer never touches these
directly (they work through the robot's distilled instructions).
"""

from __future__ import annotations

from pathlib import Path

# Standard task-control filenames (workflow-regime/task-control conventions).
DOC_NAMES = {
    "next_steps": "NEXT_STEPS.md",
    "worklog": "WORKLOG.md",
    "pending_tasks": "PENDING_TASKS.md",
}


class TaskControl:
    """Read/write task-control documents within a project directory.

    All writes are append-only or merge-guarded: existing content is preserved
    and new entries are appended under a timestamped heading, honoring the
    "只记录，不断决" (record, don't block) principle.
    """

    def __init__(self, project_dir: str | Path) -> None:
        self.project_dir = Path(project_dir)
        self.project_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, doc: str) -> Path:
        try:
            name = DOC_NAMES[doc]
        except KeyError:
            raise ValueError(f"unknown task-control doc: {doc}") from None
        return self.project_dir / name

    def read(self, doc: str) -> str:
        """Return the current content of a task-control document (empty if absent)."""
        path = self._path(doc)
        if not path.exists():
            return ""
        return path.read_text(encoding="utf-8")

    def append(self, doc: str, entry: str) -> None:
        """Append a timestamped entry to a task-control document."""
        path = self._path(doc)
        with path.open("a", encoding="utf-8") as f:
            f.write(f"\n## {_now()}\n{entry}\n")

    def init(self, doc: str) -> None:
        """Create the document with a header if it does not exist."""
        path = self._path(doc)
        if not path.exists():
            path.write_text(f"# {path.name}\n", encoding="utf-8")


def _now() -> str:
    import datetime

    return datetime.datetime.now().isoformat(timespec="seconds")