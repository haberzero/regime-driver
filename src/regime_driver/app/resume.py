"""Crash-resume support: replay the reporter journal to find the resume point.

A drive run records node progression in the reporter journal (``kind`` =
``node_enter`` / ``node_done``). If the process dies mid-run, the last node
that entered but never completed is the natural resume point: re-running the
flow from that node (with a fresh session) continues the work — the produced
files persist on disk, so earlier nodes need not be re-executed.
"""

from __future__ import annotations

import json
from pathlib import Path


def resume_node(journal_path: str | Path) -> str | None:
    """Return the first node that entered but never completed.

    Reads a reporter journal (JSONL, ``regime.report.v1`` schema). A node is
    "incomplete" when a ``node_enter`` record has no matching ``node_done``
    record. Returns None when the journal is empty, unreadable, or shows a
    fully completed run (nothing to resume).
    """
    path = Path(journal_path)
    if not path.is_file():
        return None
    entered: list[str] = []
    done: set[str] = set()
    saw_outcome = False
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                kind = rec.get("kind")
                node = rec.get("node")
                if kind == "node_enter" and node:
                    entered.append(node)
                elif kind == "node_done" and node:
                    done.add(node)
                elif kind == "outcome":
                    saw_outcome = True
    except Exception:
        return None
    if saw_outcome:
        # a terminal outcome record means the run finished; nothing to resume
        return None
    for node in entered:
        if node not in done:
            return node
    return None


def resume_context(original: str, node: str) -> str:
    """Augment the drive context for a resumed run (operator visibility)."""
    return f"（续跑：从节点 {node} 继续，先前完成的节点已跳过）\n{original}"
