"""Structured event ledger (JSONL append-only)."""

from __future__ import annotations

import datetime
import json
from pathlib import Path


class Ledger:
    """Append-only JSONL event log for auditability and self-improvement.

    Thread-safe for a single process; writes are appended with flush.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = str(path) if path else None
        self._fh = None
        if self.path:
            self._fh = open(self.path, "a", encoding="utf-8", buffering=1)

    def append(self, event: str, **fields) -> None:
        record = {"event": event, "ts": _now(), "source": "regime-driver"}
        record.update(fields)
        if self._fh is not None:
            self._fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def close(self) -> None:
        if self._fh is not None:
            self._fh.close()
            self._fh = None

    def __enter__(self) -> "Ledger":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _now() -> str:
    return datetime.datetime.now().isoformat(timespec="seconds")