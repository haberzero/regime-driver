"""Tests for the read-only observation window (regime web): snapshot collection
and the HTTP endpoints. Pure consumer — no write endpoint is ever exposed.
"""

from __future__ import annotations

import json
import threading
import urllib.request

import pytest

from regime_driver.app.observe import (
    ObservationSnapshot,
    start_observation_thread,
)


def _collect_fixture() -> tuple[ObservationSnapshot, dict]:
    """A snapshot with injected status/report fns (no live worker needed)."""
    snap = ObservationSnapshot(
        base="http://127.0.0.1:4097",
        journal=None,
        ledger=None,
        tasks_dir=None,
        status_fn=lambda: json.dumps({
            "healthy": True, "base": "http://127.0.0.1:4097",
            "busy_sessions": 1,
            "sessions": [{"id": "s1", "agent": "developer", "status": "busy"}],
            "flows": [{"name": "code_workflow", "nodes": 6}],
        }),
        report_fn=lambda: json.dumps({"summary": {"complete": 1}}),
    )
    return snap, {}


def test_snapshot_collect_shapes():
    snap, _ = _collect_fixture()
    data = snap.collect()
    assert data["base"] == "http://127.0.0.1:4097"
    assert data["status"]["healthy"] is True
    assert data["status"]["busy_sessions"] == 1
    assert data["report"]["summary"]["complete"] == 1
    assert data["ledger_tail"] == []
    assert data["journal_tail"] == []
    assert isinstance(data["ts"], float)


def test_snapshot_never_raises_on_bad_sources(tmp_path):
    # a missing ledger/journal + a failing status fn must not crash collection
    snap = ObservationSnapshot(
        base="http://x",
        journal=tmp_path / "nope.jsonl",
        ledger=tmp_path / "nope.jsonl",
        status_fn=lambda: "not json at all",
        report_fn=lambda: "{}",
    )
    data = snap.collect()
    assert data["status"] == {}
    assert data["ledger_tail"] == []
    assert data["journal_tail"] == []


def test_http_endpoints_read_only():
    snap, _ = _collect_fixture()
    server, thread = start_observation_thread(
        "http://127.0.0.1:4097", port=0, status_fn=snap._status_fn,
        report_fn=snap._report_fn)
    port = server.server_address[1]
    try:
        # /api/status -> healthy
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/status",
                                    timeout=10) as r:
            data = json.loads(r.read())
        assert data["healthy"] is True
        # /api/snapshot -> full shape
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/snapshot",
                                    timeout=10) as r:
            snap_all = json.loads(r.read())
        assert snap_all["status"]["busy_sessions"] == 1
        # /api -> endpoint list
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api", timeout=10) as r:
            idx = json.loads(r.read())
        assert "/api/snapshot" in idx["endpoints"]
        # / -> HTML panel
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/", timeout=10) as r:
            body = r.read().decode("utf-8")
        assert "regime-driver 观察窗" in body
    finally:
        server.shutdown()
        server.server_close()


def test_only_get_methods_exposed():
    """The observation window must never accept write methods."""
    snap, _ = _collect_fixture()
    server, thread = start_observation_thread(
        "http://127.0.0.1:4097", port=0, status_fn=snap._status_fn,
        report_fn=snap._report_fn)
    port = server.server_address[1]
    try:
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/api/snapshot", method="POST", data=b"{}")
        try:
            urllib.request.urlopen(req, timeout=10)
            raise AssertionError("POST should not be accepted")
        except urllib.error.HTTPError as exc:
            assert exc.code in (405, 501)  # method not allowed / unimplemented
    finally:
        server.shutdown()
        server.server_close()


def test_html_escapes_user_content():
    """XSS guard: user/LLM content (flow names, session text, ledger lines) must
    never render as HTML — every interpolated value is escaped."""
    from regime_driver.app.observe import _render_html

    evil = "<script>alert(1)</script>"
    data = {
        "base": "http://x",
        "status": {
            "healthy": True, "base": "http://x",
            "sessions": [{"id": evil, "agent": evil, "status": "busy"}],
            "flows": [{"name": evil, "nodes": 6}],
        },
        "report": {"summary": {"note": evil}},
        "ledger_tail": [f'{{"event": "{evil}"}}'],
        "journal_tail": [evil],
    }
    body = _render_html(data)
    assert "<script>" not in body, "raw <script> must be escaped in HTML panel"
    assert "&lt;script&gt;" in body, "escaped script must appear"
    # user content still visible in escaped form
    assert "alert(1)" in body
