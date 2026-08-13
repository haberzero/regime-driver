"""Tests for the process-external supervisor core (pure decision logic)."""

from __future__ import annotations

import time

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
    _parse_meta_verdict,
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


def test_session_watch_first_observe_establishes_baseline():
    # first observe must never false-stall (last_message_ts starts at 0)
    w = SessionWatch()
    assert w.observe(now=100.0, busy=True) is False
    assert w.last_message_ts == 100.0


def test_session_watch_not_stalled_within_stall_window():
    # frozen & busy but only 30s into the 60s window -> NOT stalled (negative case)
    w = SessionWatch(last_message_ts=100.0)
    assert w.is_stalled(now=100.0 + 30.0, stall_sec=60.0, busy=True) is False


def test_session_watch_stall_detection_after_window():
    # frozen & busy continuously past stall_sec -> stalled exactly once
    w = SessionWatch(last_message_ts=100.0)
    assert w.is_stalled(now=100.0, stall_sec=60.0, busy=True) is False
    assert w.is_stalled(now=100.0 + 61.0, stall_sec=60.0, busy=True) is True
    # window consumed: no re-fire on the next poll while still frozen
    assert w.is_stalled(now=100.0 + 62.0, stall_sec=60.0, busy=True) is False


def test_session_watch_sse_activity_resets_window():
    # a long deep-reasoning generation streams SSE deltas: SSE activity must
    # keep the session alive, never stalled.
    w = SessionWatch(last_message_ts=100.0)
    # SSE delta at +29s resets the window; +30s poll sees no stall
    assert w.is_stalled(now=100.0 + 30.0, stall_sec=60.0, busy=True,
                        activity_ts=100.0 + 29.0) is False
    # SSE keeps arriving (at +69s); +70s poll still no stall
    assert w.is_stalled(now=100.0 + 70.0, stall_sec=60.0, busy=True,
                        activity_ts=100.0 + 69.0) is False
    # SSE stops at +69s; frozen for 60s afterwards (at +130s) -> finally stalled
    assert w.is_stalled(now=100.0 + 130.0, stall_sec=60.0, busy=True,
                        activity_ts=100.0 + 69.0) is True


def test_session_watch_recovery_resets_consecutive_stalls():
    # a stall window fires once; a recovery (idle) resets the consecutive
    # counter so a later separate episode starts fresh (no cross-episode
    # escalation leak).
    w = SessionWatch(last_message_ts=100.0)
    assert w.is_stalled(now=100.0 + 61.0, stall_sec=60.0, busy=True) is True
    assert w.consecutive_stalls == 1
    # session goes idle -> recovery
    assert w.is_stalled(now=100.0 + 62.0, stall_sec=60.0, busy=False) is False
    assert w.consecutive_stalls == 0


def test_is_progress_event():
    from regime_driver.app.sse_activity import is_progress_event
    # connection handshake + keepalive must NOT count as activity
    assert is_progress_event("server.connected") is False
    assert is_progress_event("server.heartbeat") is False
    assert is_progress_event(None) is False
    # genuine progress events count
    assert is_progress_event("message.part.delta") is True
    assert is_progress_event("message.completed") is True
    assert is_progress_event("session.idle") is True


def test_session_watch_not_stalled_when_idle():
    w = SessionWatch(last_message_ts=100.0)
    assert w.is_stalled(now=200.0, stall_sec=60.0, busy=False) is False


# -- meta-analysis (real model judges verdict, deterministic-gated) -----------


def test_parse_meta_verdict_valid():
    data = _parse_meta_verdict(
        '{"verdict":"looping","confidence":0.8,"recommended_action":"abort",'
        '"reason":"looping"}')
    assert data["verdict"] == "looping"
    assert data["recommended_action"] == "abort"
    assert data["confidence"] == 0.8


def test_parse_meta_verdict_tolerates_fence_and_prose():
    data = _parse_meta_verdict(
        'Here is my analysis.\n```json\n'
        '{"verdict":"stalled","confidence":0.6,"recommended_action":"abort",'
        '"reason":"no output"}\n```\nDone.')
    assert data["verdict"] == "stalled"


def test_parse_meta_verdict_missing_key_raises():
    import pytest
    with pytest.raises(ValueError):
        _parse_meta_verdict('{"verdict":"stalled","confidence":0.6}')


def test_parse_meta_verdict_no_json_raises():
    import pytest
    with pytest.raises(ValueError):
        _parse_meta_verdict("I cannot provide a structured answer.")


class _MetaClient:
    """Stub client: returns a scripted meta reply and records the call."""

    def __init__(self, reply="", fail=False):
        self.reply = reply
        self.fail = fail
        self.calls = 0
        self.reads = []

    def create_session(self, title):
        return "meta-session"

    def ask_and_get_text(self, sid, prompt, agent, model=None):
        self.calls += 1
        if self.fail:
            raise RuntimeError("model down")
        return self.reply

    def read_messages(self, sid):
        self.reads.append(sid)
        return []


def test_meta_analyze_disabled_returns_none():
    sup = Supervisor(_MetaClient(), session_id="s1", meta_enabled=False)
    assert sup.meta_analyze() is None


def test_meta_analyze_valid_verdict_passes_gate():
    client = _MetaClient(reply='{"verdict":"looping","confidence":0.8,'
                                 '"recommended_action":"abort","reason":"looping"}')
    sup = Supervisor(client, session_id="s1", meta_enabled=True, meta_model="m")
    verdict, action, confidence = sup.meta_analyze()
    assert (verdict, action) == ("looping", "abort")
    assert confidence == 0.8


def test_meta_analyze_bad_verdict_rejected_falls_back_none():
    # action not allowed for verdict -> gate rejects -> None (deterministic fallback)
    client = _MetaClient(reply='{"verdict":"normal","confidence":0.9,'
                               '"recommended_action":"abort","reason":"?"}')
    sup = Supervisor(client, session_id="s1", meta_enabled=True, meta_model="m")
    assert sup.meta_analyze() is None


def test_meta_analyze_model_error_returns_none():
    sup = Supervisor(_MetaClient(fail=True), session_id="s1",
                     meta_enabled=True, meta_model="m")
    assert sup.meta_analyze() is None



def test_verdict_for_stall_escalates():
    from regime_driver.supervisor import _verdict_for_stall
    assert _verdict_for_stall(1) == ("stalled", L2_ABORT, 0.6)
    assert _verdict_for_stall(3) == ("error", L4_RESTART, 0.8)
    assert _verdict_for_stall(4) == ("escalate", L5_HUMAN, 0.9)


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

    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        rep = Reporter(journal_path=Path(td) / "j.jsonl", project_id="supervisor")
        sup = Supervisor(OpenCodeClient("http://x:4097"), rep, session_id="s1")
        n = sup.ingest_events(max_events=2, stream_timeout=5)
        assert n == 2
        recs = rep.journal_slice()
        assert len(recs) == 2  # both events recorded to the journal


def test_supervisor_ingests_events_data_type_format(monkeypatch):
    """Regression (2026-08-13 quality-run): the real opencode 1.18.11 SSE
    stream emits the event type inside the `data` JSON with NO `event:` line.
    Before the event_stream fix, `raw["event"]` was always None, so T2
    liveness (`_last_activity_ts`) never updated and streaming deltas flooded
    the journal (90% noise). With the fix the event type must surface and
    `_last_activity_ts` must advance on genuine progress."""
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

    sse = (
        "data: {\"type\": \"server.connected\", \"properties\": {}}\n\n"
        "data: {\"type\": \"message.part.delta\", \"properties\": {\"sessionID\": \"s1\"}}\n\n"
    )
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, **kw: _Resp(sse))

    from regime_driver.app.reporter import Reporter
    from regime_driver.infra.opencode import OpenCodeClient

    import tempfile
    from pathlib import Path
    with tempfile.TemporaryDirectory() as td:
        rep = Reporter(journal_path=Path(td) / "j.jsonl", project_id="supervisor")
        sup = Supervisor(OpenCodeClient("http://x:4097"), rep, session_id="s1")
        n = sup.ingest_events(max_events=2, stream_timeout=5)
        assert n == 2
        recs = rep.journal_slice()
        # the delta is noise -> dropped; only the lifecycle event is recorded
        assert len(recs) == 1
        assert recs[0]["event_type"] == "server.connected"
        # genuine streaming progress advanced the T2 liveness timestamp
        assert sup._last_activity_ts > 0.0


def test_supervisor_ingest_sse_error_is_audited():
    """Regression (A: silent failure): a transient SSE failure must be
    recorded as an audit event, not silently swallowed — otherwise T2
    liveness degradation is invisible (the 2026-08-13 root cause was exactly
    such a silent path)."""
    from regime_driver.app.reporter import Reporter
    from regime_driver.supervisor import Supervisor

    import tempfile
    from pathlib import Path

    class BoomClient:
        def event_stream(self, reconnect=False, max_retries=1):
            raise RuntimeError("stream dropped")

    with tempfile.TemporaryDirectory() as td:
        rep = Reporter(journal_path=Path(td) / "j.jsonl", project_id="supervisor")
        sup = Supervisor(BoomClient(), rep, session_id="s1")
        n = sup.ingest_events(max_events=2, stream_timeout=5)
        assert n == 0
        recs = rep.journal_slice()
        assert any(r["event_type"] == "sse_error" for r in recs)


def test_supervisor_ingest_unresolved_type_is_audited():
    """Regression (A): events with no resolvable type must be counted and
    throttled-audited so a future event-stream regression is visible in the
    journal (T2 liveness would otherwise silently degrade)."""
    from regime_driver.app.reporter import Reporter
    from regime_driver.supervisor import Supervisor

    import tempfile
    from pathlib import Path

    class NoTypeClient:
        def event_stream(self, reconnect=False, max_retries=1):
            yield {"event": None, "data": {"id": "x", "properties": {}}}

    with tempfile.TemporaryDirectory() as td:
        rep = Reporter(journal_path=Path(td) / "j.jsonl", project_id="supervisor")
        sup = Supervisor(NoTypeClient(), rep, session_id="s1")
        sup._last_liveness_log = 0.0
        n = sup.ingest_events(max_events=5, stream_timeout=5)
        assert n == 1
        assert sup._events_no_type == 1
        recs = rep.journal_slice()
        assert any(r["event_type"] == "sse_type_unresolved" for r in recs)


class _StallLoopClient:
    """Scripted worker for the Supervisor run-loop T2 test.

    ``events`` yields per-poll SSE streams; each stream starts with
    ``server.connected`` (the real per-poll handshake) followed by any extra
    events the test supplies. ``progress`` toggles whether genuine progress
    events are emitted between polls.
    """

    def __init__(self, progress: bool):
        self.progress = progress
        self.aborts = 0
        self._t = 0.0

    def health(self):
        return True

    def event_stream(self, reconnect=False, max_retries=1):
        yield {"event": "server.connected", "data": {}}
        if self.progress:
            yield {"event": "message.part.delta", "data": {"sessionID": "s1"}}

    def session_status(self, sid):
        return "busy"

    def session_tokens(self, sid):
        return 0, 5  # frozen output across polls

    def abort_session(self, sid):
        self.aborts += 1


def test_supervisor_t2_fires_on_genuine_stall_not_on_handshake():
    """Regression for the live-loop wiring: per-poll `server.connected` must not
    count as session activity (or T2 would never fire); a genuinely frozen-busy
    session must escalate after stall_sec."""
    from regime_driver.supervisor import Supervisor, L2_ABORT

    # stall=false: worker always streams progress -> T2 must NEVER fire
    sup_ok = Supervisor(_StallLoopClient(progress=True), session_id="s1",
                        stall_sec=0.1, health_poll_sec=0.01)
    for _ in range(12):
        sup_ok.ingest_events(max_events=5, stream_timeout=0.05)
        if sup_ok.watch.is_stalled(
                time.time(), sup_ok.stall_sec, True,
                activity_ts=sup_ok._last_activity_ts):
            break
    assert sup_ok.watch.consecutive_stalls == 0

    # stall=true: only server.connected handshakes, never progress -> T2 fires
    # (the frozen session stalls past stall_sec and escalates to abort)
    sup_bad = Supervisor(_StallLoopClient(progress=False), session_id="s1",
                         stall_sec=0.1, health_poll_sec=0.01)
    t0 = time.monotonic()
    fired = False
    while time.monotonic() - t0 < 2.0:
        sup_bad.ingest_events(max_events=5, stream_timeout=0.05)
        if sup_bad.watch.is_stalled(
                time.time(), sup_bad.stall_sec, True,
                activity_ts=sup_bad._last_activity_ts):
            fired = True
            break
    assert fired, "T2 must fire on a genuinely frozen-busy session"
    assert sup_bad.watch.consecutive_stalls >= 1
