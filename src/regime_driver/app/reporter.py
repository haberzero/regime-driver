"""Report bus: rules-based, append-only journal + incremental rollups (WORK_PLAN4 III).

The god dialog / a macro project manager needs *always-available, traceable,
differentiable* global information — without re-polling the CLI or being unable
to see state. This is the **Journal + Report Bus**:

* **Attribution keys** distinguish the three observation faces of the same work:
  a state-machine instance (``sm_id``) == a workflow (``wf_id``) == a driver
  session (``session_id``). A report can slice by any of them.
* **Ingestion** (``ingest``) normalizes any event (from the internal bus, a
  ledger write point, or the worker SSE stream) into a versioned
  ``ReportRecord`` with those keys.
* **Storage**: an append-only JSONL journal keeps the full history (traceability
  length), while incremental **rollups** keep per-workflow counters O(1) to query.
* **Query** (``journal_slice`` / ``rollup``) is on-demand and bounded.

Pure-ish: only I/O is the optional append-only journal file. No model in the loop.
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

REPORT_SCHEMA = "regime.report.v1"


@dataclass
class ReportRecord:
    """A single normalized, attribution-keyed report record."""

    schema: str = REPORT_SCHEMA
    ts: float = field(default_factory=time.time)
    project_id: str = "default"
    wf_id: str | None = None
    session_id: str | None = None
    sm_id: str | None = None
    kind: str = "event"        # node_enter|node_done|reviewer_verdict|outcome|stall|milestone|session|worker
    event_type: str | None = None
    node: str | None = None
    phase: str | None = None
    outcome: str | None = None
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


class Rollup:
    """Incremental per-workflow counters (O(1) query, no journal scan)."""

    def __init__(self, project_id: str, wf_id: str) -> None:
        self.project_id = project_id
        self.wf_id = wf_id
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self.outcome: str | None = None
        self.current_node: str | None = None
        self.current_phase: str | None = None
        self.nodes_entered = 0
        self.nodes_done = 0
        self.verdicts: dict[str, int] = {}
        self.kinds: dict[str, int] = {}

    def apply(self, r: ReportRecord) -> None:
        if self.started_at is None:
            self.started_at = r.ts
        self.kinds[r.kind] = self.kinds.get(r.kind, 0) + 1
        if r.kind == "node_enter":
            self.nodes_entered += 1
            self.current_node = r.node
            self.current_phase = r.phase
        elif r.kind == "node_done":
            self.nodes_done += 1
        elif r.kind == "reviewer_verdict":
            v = (r.detail or {}).get("verdict")
            if v:
                self.verdicts[v] = self.verdicts.get(v, 0) + 1
        elif r.kind == "outcome":
            self.outcome = r.outcome
            self.finished_at = r.ts

    def to_dict(self) -> dict:
        elapsed = None
        if self.started_at is not None:
            end = self.finished_at or time.time()
            elapsed = round(end - self.started_at, 1)
        return {
            "project_id": self.project_id,
            "wf_id": self.wf_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "outcome": self.outcome,
            "current_node": self.current_node,
            "current_phase": self.current_phase,
            "nodes_entered": self.nodes_entered,
            "nodes_done": self.nodes_done,
            "verdicts": self.verdicts,
            "kinds": self.kinds,
            "elapsed_sec": elapsed,
        }


class Reporter:
    """Rules-based journal + rollup bus. Thread-safe; append-only journal."""

    def __init__(self, journal_path: str | Path | None = None,
                 project_id: str = "default") -> None:
        self.project_id = project_id
        self.journal_path = Path(journal_path) if journal_path else None
        self._lock = threading.Lock()
        self._rollups: dict[tuple[str, str], Rollup] = {}
        self._fh = None
        if self.journal_path:
            self.journal_path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = self.journal_path.open("a", encoding="utf-8")

    def ingest(self, *, kind: str = "event", project_id: str | None = None,
               wf_id: str | None = None,
               session_id: str | None = None, sm_id: str | None = None,
               node: str | None = None, phase: str | None = None,
               outcome: str | None = None, event_type: str | None = None,
               detail: dict | None = None, ts: float | None = None) -> ReportRecord:
        """Normalize + record one event (internal bus / ledger write point)."""
        record = ReportRecord(
            ts=ts if ts is not None else time.time(),
            project_id=project_id if project_id is not None else self.project_id,
            wf_id=wf_id, session_id=session_id, sm_id=sm_id,
            kind=kind, event_type=event_type, node=node, phase=phase,
            outcome=outcome, detail=dict(detail or {}),
        )
        with self._lock:
            self._apply(record)
            if self._fh is not None:
                self._fh.write(json.dumps(record.to_dict(), ensure_ascii=False) + "\n")
                self._fh.flush()
        return record

    def ingest_worker_event(self, raw: dict, *, wf_id: str | None = None,
                            session_id: str | None = None,
                            project_id: str | None = None) -> ReportRecord | None:
        """Normalize an opencode SSE worker event (from `event_stream`) into a record.

        Streaming part events (``message.part.delta`` / ``message.part.updated``)
        are high-frequency noise that would drown the journal (a single long
        generation emits hundreds); they are evidence of liveness only, so they
        are dropped from the journal. Meaningful lifecycle events
        (``server.connected``, ``session.idle``, ``message.completed``, ...) are
        kept. Returns None for dropped events.
        """
        etype = raw.get("event")
        if etype in ("message.part.delta", "message.part.updated"):
            return None
        data = raw.get("data") if isinstance(raw.get("data"), dict) else {}
        return self.ingest(
            kind="worker",
            event_type=etype,
            wf_id=wf_id,
            session_id=session_id or data.get("sessionID") or data.get("session_id"),
            sm_id=None,
            project_id=project_id if project_id is not None else self.project_id,
            detail=data,
        )

    # -- internals ----------------------------------------------------------

    def _apply(self, record: ReportRecord) -> None:
        key = (record.project_id, record.wf_id or "")
        rollup = self._rollups.get(key)
        if rollup is None:
            rollup = Rollup(record.project_id, record.wf_id or "")
            self._rollups[key] = rollup
        rollup.apply(record)

    # -- queries ------------------------------------------------------------

    def rollup(self, project_id: str | None = None, wf_id: str | None = None) -> list[dict]:
        """Return rollups, optionally filtered by project/workflow."""
        out = []
        with self._lock:
            for (pid, wid), rollup in self._rollups.items():
                if project_id is not None and pid != project_id:
                    continue
                if wf_id is not None and wid != wf_id:
                    continue
                out.append(rollup.to_dict())
        return sorted(out, key=lambda d: (d["project_id"], d["wf_id"]))

    def journal_slice(self, *, project_id: str | None = None, wf_id: str | None = None,
                      since: float | None = None, limit: int | None = None) -> list[dict]:
        """Read a bounded slice of the append-only journal (empty if no journal)."""
        if self.journal_path is None or not self.journal_path.exists():
            return []
        with self._lock:
            records = []
            with self.journal_path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    if project_id is not None and rec.get("project_id") != project_id:
                        continue
                    if wf_id is not None and rec.get("wf_id") != wf_id:
                        continue
                    if since is not None and (rec.get("ts") or 0) < since:
                        continue
                    records.append(rec)
        if limit is not None and limit > 0:
            records = records[-limit:]
        return records

    def load(self) -> int:
        """Replay the append-only journal into rollups (rebuild on demand).

        Used when opening an existing journal (e.g. `regime report`) so rollups
        reflect the persisted history without live ingestion. Returns record count.
        """
        if self.journal_path is None or not self.journal_path.exists():
            return 0
        n = 0
        _keys = ReportRecord.__dataclass_fields__.keys()
        with self._lock:
            # make load() idempotent: rebuild rollups from scratch, not accumulate
            self._rollups.clear()
            with self.journal_path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    record = ReportRecord(**{k: data.get(k) for k in _keys})
                    self._apply(record)
                    n += 1
        return n

    def retain(self, max_age_sec: float | None = None, max_records: int | None = None) -> int:
        """Prune the journal by age and/or record count (retention policy).

        Drops records older than ``max_age_sec`` and keeps only the tail
        ``max_records``, rewriting the journal in place under the lock. Returns
        the number of records removed. Raises if no journal is configured.
        """
        if self.journal_path is None or not self.journal_path.exists():
            raise ValueError("no journal configured to prune")
        now = time.time()
        kept = []
        removed = 0
        with self._lock:
            with self.journal_path.open(encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        removed += 1
                        continue
                    ts = rec.get("ts") or 0
                    if max_age_sec is not None and (now - ts) > max_age_sec:
                        removed += 1
                        continue
                    kept.append(line)
            if max_records is not None and len(kept) > max_records:
                overflow = len(kept) - max_records
                kept = kept[overflow:]
                removed += overflow
            tmp = self.journal_path.with_suffix(".jsonl.tmp")
            tmp.write_text("\n".join(kept) + ("\n" if kept else ""), encoding="utf-8")
            tmp.replace(self.journal_path)
            # the old append handle now points at a deleted inode: reopen it so a
            # subsequent ingest() keeps writing to the (pruned) journal
            if self._fh is not None:
                try:
                    self._fh.close()
                except Exception:
                    pass
                self._fh = self.journal_path.open("a", encoding="utf-8")
            # refresh in-memory rollups to match the pruned journal
            self._rollups.clear()
            for line in kept:
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                self._apply(ReportRecord(**{k: data.get(k)
                                            for k in ReportRecord.__dataclass_fields__.keys()}))
        return removed

    def close(self) -> None:
        with self._lock:
            if self._fh is not None:
                self._fh.close()
                self._fh = None

    def __enter__(self) -> "Reporter":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
