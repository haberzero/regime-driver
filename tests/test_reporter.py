"""Tests for the report bus (app/reporter.py)."""

from __future__ import annotations

import json

from regime_driver.app.reporter import Reporter, REPORT_SCHEMA


def test_ingest_normalizes_attribution_keys() -> None:
    r = Reporter()
    rec = r.ingest(kind="node_enter", wf_id="w1", session_id="s1", sm_id="sm1",
                   node="design", phase="agent", event_type="node_enter")
    assert rec.schema == REPORT_SCHEMA
    assert rec.project_id == "default"
    assert rec.wf_id == "w1"
    assert rec.session_id == "s1"
    assert rec.sm_id == "sm1"
    assert rec.node == "design"


def test_rollup_accumulates() -> None:
    r = Reporter()
    r.ingest(kind="node_enter", wf_id="w1", node="design", phase="agent")
    r.ingest(kind="node_done", wf_id="w1", node="design")
    r.ingest(kind="reviewer_verdict", wf_id="w1", node="design",
             detail={"verdict": "advance"})
    r.ingest(kind="reviewer_verdict", wf_id="w1", node="design",
             detail={"verdict": "advance"})
    r.ingest(kind="outcome", wf_id="w1", outcome="complete")
    roll = r.rollup(wf_id="w1")[0]
    assert roll["nodes_entered"] == 1
    assert roll["nodes_done"] == 1
    assert roll["verdicts"] == {"advance": 2}
    assert roll["outcome"] == "complete"
    assert roll["current_node"] == "design"


def test_rollup_isolation_by_workflow() -> None:
    r = Reporter()
    r.ingest(kind="node_enter", wf_id="w1")
    r.ingest(kind="node_enter", wf_id="w2")
    assert len(r.rollup()) == 2
    assert len(r.rollup(wf_id="w1")) == 1


def test_worker_event_ingestion() -> None:
    r = Reporter()
    rec = r.ingest_worker_event({"event": "session.idle", "data": {"sessionID": "abc"}})
    assert rec.kind == "worker"
    assert rec.event_type == "session.idle"
    assert rec.session_id == "abc"


def test_journal_persistence(tmp_path) -> None:
    path = tmp_path / "report.jsonl"
    r = Reporter(journal_path=path)
    r.ingest(kind="node_enter", wf_id="w1", node="a")
    r.ingest(kind="node_enter", wf_id="w1", node="b")
    r.close()
    # a fresh Reporter over the same journal reads both records
    r2 = Reporter(journal_path=path)
    recs = r2.journal_slice(wf_id="w1")
    assert len(recs) == 2
    assert recs[0]["node"] == "a"
    assert recs[1]["node"] == "b"
    # bounded slice keeps the tail
    assert len(r2.journal_slice(wf_id="w1", limit=1)) == 1


def test_load_replays_rollups(tmp_path) -> None:
    path = tmp_path / "report.jsonl"
    r = Reporter(journal_path=path)
    r.ingest(kind="node_enter", wf_id="w1", node="a")
    r.ingest(kind="node_done", wf_id="w1", node="a")
    r.ingest(kind="outcome", wf_id="w1", outcome="complete")
    r.close()
    r2 = Reporter(journal_path=path)
    assert r2.load() == 3
    roll = r2.rollup(wf_id="w1")[0]
    assert roll["nodes_entered"] == 1
    assert roll["nodes_done"] == 1
    assert roll["outcome"] == "complete"


def test_retain_by_age_and_count(tmp_path) -> None:
    path = tmp_path / "report.jsonl"
    r = Reporter(journal_path=path)
    r.ingest(kind="node_enter", wf_id="w1", ts=1.0)
    r.ingest(kind="node_enter", wf_id="w1", ts=2.0)
    r.ingest(kind="node_enter", wf_id="w1", ts=3.0)
    r.close()
    r2 = Reporter(journal_path=path)
    # keep only the tail 1 record
    removed = r2.retain(max_records=1)
    assert removed == 2
    assert len(r2.journal_slice()) == 1
    assert r2.journal_slice()[0]["ts"] == 3.0
    # rollups rebuilt to match
    assert r2.rollup(wf_id="w1")[0]["nodes_entered"] == 1


def test_ingest_after_retain_still_writes(tmp_path) -> None:
    """After retain() replaces the journal, ingest() must append to the new file."""
    path = tmp_path / "report.jsonl"
    r = Reporter(journal_path=path)
    r.ingest(kind="node_enter", wf_id="w1", ts=1.0)
    r.ingest(kind="node_enter", wf_id="w1", ts=2.0)
    removed = r.retain(max_records=1)
    assert removed == 1
    r.ingest(kind="outcome", wf_id="w1", outcome="complete", ts=3.0)
    r.close()
    r2 = Reporter(journal_path=path)
    assert len(r2.journal_slice()) == 2
    assert r2.journal_slice()[-1]["kind"] == "outcome"


def test_journal_slice_since_filter(tmp_path) -> None:
    path = tmp_path / "report.jsonl"
    r = Reporter(journal_path=path)
    r.ingest(kind="node_enter", wf_id="w1", ts=1000.0)
    r.ingest(kind="node_done", wf_id="w1", ts=2000.0)
    r.close()
    r2 = Reporter(journal_path=path)
    recs = r2.journal_slice(since=1500.0)
    assert len(recs) == 1
    assert recs[0]["kind"] == "node_done"
