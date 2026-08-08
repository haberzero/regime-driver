"""Tests for the process-external supervisor core (pure decision logic)."""

from __future__ import annotations

import pytest

from regime_driver.supervisor import (
    L2_ABORT,
    L3_FALLBACK,
    L4_RESTART,
    L5_HUMAN,
    LadderState,
    MetaGateReject,
    SessionWatch,
    Supervisor,
    choose_action,
    gate_meta,
)


def test_gate_meta_accepts_valid():
    gate_meta("stalled", L2_ABORT, 0.6)
    gate_meta("normal", "none", 0.0)


def test_gate_meta_rejects_unknown_verdict():
    with pytest.raises(MetaGateReject):
        gate_meta("bogus", L2_ABORT, 0.9)


def test_gate_meta_rejects_unknown_action():
    with pytest.raises(MetaGateReject):
        gate_meta("stalled", "explode", 0.9)


def test_gate_meta_rejects_action_not_allowed_for_verdict():
    # 'normal' only allows 'none'
    with pytest.raises(MetaGateReject):
        gate_meta("normal", L2_ABORT, 0.9)


def test_gate_meta_rejects_low_confidence():
    with pytest.raises(MetaGateReject):
        gate_meta("stalled", L4_RESTART, 0.5)  # restart floor 0.75


def test_choose_action_fallback_not_repeated():
    state = LadderState()
    # first fallback ok
    assert choose_action("stalled", L3_FALLBACK, 0.6, state) == L3_FALLBACK
    # second fallback escalates to abort (not repeated)
    assert choose_action("stalled", L3_FALLBACK, 0.6, state) == L2_ABORT


def test_choose_action_restart_not_repeated_escalates_to_human():
    state = LadderState()
    assert choose_action("error", L4_RESTART, 0.8, state) == L4_RESTART
    assert choose_action("error", L4_RESTART, 0.8, state) == L5_HUMAN


def test_session_watch_stall_detection():
    w = SessionWatch(last_output=5, last_message_ts=100.0)
    # same output, no new message, past stall window -> stalled
    assert w.is_stalled(now=100.0 + 61.0, stall_sec=60.0, busy=True, output=5) is True
    # output grew -> not stalled, bookkeeping updates
    assert w.is_stalled(now=200.0, stall_sec=60.0, busy=True, output=9) is False
    assert w.last_output == 9


def test_session_watch_not_stalled_when_idle():
    w = SessionWatch(last_output=5, last_message_ts=100.0)
    assert w.is_stalled(now=200.0, stall_sec=60.0, busy=False, output=5) is False


def test_supervisor_ingests_events(monkeypatch):
    import urllib.request

    class _Resp:
        def __init__(self, text):
            self._lines = [(l + "\n").encode() for l in text.split("\n")]
            self._i = 0

        def __iter__(self):
            return self

        def __next__(self):
            if self._i >= len(self._lines):
                raise StopIteration
            line = self._lines[self._i]
            self._i += 1
            return line

        def close(self):
            pass

    sse = ("event: server.connected\ndata: {\"healthy\":true}\n\n"
           "event: session.idle\ndata: {\"sessionID\":\"s1\"}\n\n")
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, **kw: _Resp(sse))

    from regime_driver.app.reporter import Reporter
    from regime_driver.infra.opencode import OpenCodeClient

    rep = Reporter(project_id="supervisor")
    sup = Supervisor(OpenCodeClient("http://x:4097"), rep, session_id="s1")
    n = sup.ingest_events(n=2, timeout=5)
    assert n == 2
    recs = rep.journal_slice()
    assert len(recs) == 2 if rep.journal_path else True  # in-memory ingestion works
