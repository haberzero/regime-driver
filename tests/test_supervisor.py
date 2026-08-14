"""Tests for the process-external supervisor core (pure decision logic)."""

from __future__ import annotations

import time

import pytest

from regime_driver.supervisor import (
    EXTERNAL_ACTIONS,
    L2_ABORT,
    L3_FALLBACK,
    L4_RESTART,
    L5_HUMAN,
    LadderState,
    MetaGateReject,
    Supervisor,
    choose_action,
    external_policy,
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


def test_external_policy_actions_ladder():
    """Phase-1c: the external supervisor declares its OWN action order through
    the shared watchdog_policy engine (capability-set per Actor)."""
    assert list(EXTERNAL_ACTIONS) == [L2_ABORT, L3_FALLBACK, L4_RESTART, L5_HUMAN]
    p = external_policy(stall_sec=60)
    assert p.name == "external"
    assert [r.action for r in p.rules] == \
        [L2_ABORT, L3_FALLBACK, L4_RESTART, L5_HUMAN]


def test_external_policy_escalates_by_absolute_silence():
    """Behavioral redesign (phase-1c): escalation is driven by TOTAL silence
    duration (multi-level absolute rules), not by consecutive per-window counts.
    A session silent for k*stall_sec climbs to the k-th ladder rung; a recovery
    resets the ladder so the next separate episode starts fresh from abort."""
    from regime_driver.app.watchdog_policy import SessionEvidence

    p = external_policy(stall_sec=60)
    now = 1000.0

    def ev(silent_since):
        return SessionEvidence(session_id="s1", status="busy",
                               activity_ts=silent_since, now=now)

    # no silence yet -> nothing
    assert p.decide(ev(now)) is None
    # 60s silence -> abort (first rung)
    assert p.decide(ev(now - 60)) == L2_ABORT
    # same rung hit again (no recovery) -> fired-once guard -> None
    assert p.decide(ev(now - 61)) is None
    # 120s total silence -> fallback; 180s -> restart; 240s -> human (final)
    assert p.decide(ev(now - 120)) == L3_FALLBACK
    assert p.decide(ev(now - 180)) == L4_RESTART
    assert p.decide(ev(now - 240)) == L5_HUMAN
    # recovery resets the ladder
    assert p.decide(ev(now - 240), recovered=True) is None
    # fresh silence starts again from the first rung
    assert p.decide(ev(now - 60)) == L2_ABORT


def test_external_policy_rejects_action_outside_actions():
    """An operator rule action outside the policy's declared ladder fails loudly
    at construction (same engine guarantee as the in-process vocabulary)."""
    from regime_driver.app.watchdog_policy import Rule, WatchdogPolicy

    with pytest.raises(ValueError):
        WatchdogPolicy(
            actions=EXTERNAL_ACTIONS,
            rules=[Rule("bad", lambda e: True, "kill")],  # not in external ladder
        )


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


def test_meta_second_opinion_escalates_but_never_reduces():
    """Phase-1c meta semantics: intelligence may escalate the deterministic
    action (e.g. straight to human) but never reduce it — the deterministic
    policy is the safety floor and meta advises within the gate."""
    # meta recommends human -> deterministic abort is escalated to human
    client = _MetaClient(reply='{"verdict":"blocked","confidence":0.9,'
                               '"recommended_action":"human","reason":"hard block"}')
    sup = Supervisor(client, session_id="s1", meta_enabled=True, meta_model="m")
    assert sup._meta_second_opinion(L2_ABORT) == L5_HUMAN
    assert client.calls == 1

    # meta recommends nothing (normal/none) -> deterministic action preserved
    client2 = _MetaClient(reply='{"verdict":"normal","confidence":0.6,'
                                '"recommended_action":"none","reason":"ok"}')
    sup2 = Supervisor(client2, session_id="s1", meta_enabled=True, meta_model="m")
    assert sup2._meta_second_opinion(L2_ABORT) == L2_ABORT
    assert client2.calls == 1

    # meta disabled -> no model call, deterministic action used unchanged
    client3 = _MetaClient()
    sup3 = Supervisor(client3, session_id="s1", meta_enabled=False)
    assert sup3._meta_second_opinion(L4_RESTART) == L4_RESTART
    assert client3.calls == 0


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


def test_supervisor_t2_never_fires_when_streaming():
    """Regression for the live-loop wiring: per-poll `server.connected` must not
    count as session activity; a session that keeps streaming SSE progress must
    NEVER be flagged stalled by the shared policy engine."""
    from regime_driver.supervisor import Supervisor

    sup = Supervisor(_StallLoopClient(progress=True), session_id="s1",
                     stall_sec=0.1, health_poll_sec=0.01)
    for _ in range(15):
        sup.ingest_events(max_events=5, stream_timeout=0.05)
        ev, recovered = sup._evidence(sup.client.session_status("s1"))
        action = sup.policy.decide(ev, recovered=recovered)
        assert action is None, f"streaming session must never stall, got {action!r}"


def test_supervisor_t2_escalates_to_human_on_frozen_busy():
    """The independent `regime supervisor` path keeps the full T2 ladder: a
    genuinely frozen-busy session escalates abort -> fallback -> restart -> human
    through the shared watchdog_policy engine (absolute-duration rules), and the
    loop exits at L5 human."""
    from regime_driver.supervisor import Supervisor

    c = _StallFrozenClient()
    sup = Supervisor(c, session_id="s1", stall_sec=0.01, health_poll_sec=0.01,
                     deadline_sec=0.5)
    out = sup.run(once=False, supervise_sessions=True)
    assert c.aborts >= 1
    assert out == "human"


class _StallFrozenClient:
    """Frozen-busy worker: alive, never progresses, records aborts."""

    def __init__(self):
        self.aborts = 0

    def health(self):
        return True

    def event_stream(self, reconnect=False, max_retries=1):
        yield {"event": "server.connected", "data": {}}

    def session_status(self, sid):
        return "busy"

    def session_tokens(self, sid):
        return 0, 0

    def abort_session(self, sid):
        self.aborts += 1


def test_supervise_sessions_false_disables_t2():
    """drive-mode convergence: with supervise_sessions=False the external
    supervisor must NOT run the T2 session-stall ladder (the in-process watchdog
    owns session recovery); a frozen-busy session is left alone."""
    from regime_driver.supervisor import Supervisor

    c = _StallFrozenClient()
    sup = Supervisor(c, session_id="s1", stall_sec=0.01, health_poll_sec=0.01)
    # prime the silence baseline so a stall would fire immediately if T2 ran
    sup._first_busy_ts = time.time() - 100.0
    out = sup.run(once=True, supervise_sessions=False)
    assert c.aborts == 0
    assert out == "complete"


def test_supervise_sessions_true_still_fires_t2():
    """The independent `regime supervisor` path keeps the full T2 ladder: a
    frozen-busy session escalates (abort first) even when no in-process watchdog
    is present, and the loop exits at L5 human."""
    from regime_driver.supervisor import Supervisor

    c = _StallFrozenClient()
    sup = Supervisor(c, session_id="s1", stall_sec=0.01, health_poll_sec=0.01,
                     deadline_sec=0.5)
    # prime the silence baseline just past the FIRST threshold so the first
    # poll fires abort; continued freezing then climbs abort->...->human.
    sup._first_busy_ts = time.time() - (sup.stall_sec + 0.001)
    out = sup.run(once=False, supervise_sessions=True)
    assert c.aborts >= 1
    assert out == "human"


def test_supervise_sessions_false_still_enforces_deadline():
    """drive-mode convergence keeps the process-external capabilities that are
    unique to it: with supervise_sessions=False the global deadline still ends
    the loop, while the session is left alone (no T2 aborts)."""
    from regime_driver.supervisor import Supervisor

    c = _StallFrozenClient()
    sup = Supervisor(c, session_id="s1", stall_sec=0.01, health_poll_sec=0.01,
                     deadline_sec=0.05)
    out = sup.run(once=False, supervise_sessions=False)
    assert out == "timeout"
    assert c.aborts == 0


def test_meta_review_fires_reviews_journal_fires():
    """drive-mode --meta must stay alive: the external supervisor reviews each
    watchdog_fire the in-process watchdog journaled, with an independent model
    (second opinion recorded, deterministic action not overruled)."""
    from regime_driver.supervisor import Supervisor
    from regime_driver.app.reporter import Reporter

    import tempfile
    from pathlib import Path
    client = _MetaClient(
        reply='{"verdict":"looping","confidence":0.8,'
              '"recommended_action":"abort","reason":"looping"}')
    with tempfile.TemporaryDirectory() as td:
        rep = Reporter(journal_path=Path(td) / "j.jsonl", project_id="drive")
        sup = Supervisor(client, rep, session_id="s1",
                         meta_enabled=True, meta_model="m")
        # plant a watchdog_fire as the in-process watchdog would record
        rep.ingest(kind="watchdog_fire", session_id="s1", event_type="kill",
                   detail={"reason": "hard backstop"})
        sup._meta_review_fires()
        assert client.calls >= 1, "meta must review the journaled fire"
        assert client.reads, "meta evidence must read the fire's session messages"


def test_meta_review_fires_skips_non_fire_events():
    """The meta channel only reviews watchdog fires, not every journal record."""
    from regime_driver.supervisor import Supervisor
    from regime_driver.app.reporter import Reporter

    import tempfile
    from pathlib import Path
    client = _MetaClient(reply='{"verdict":"normal","confidence":0.0,'
                               '"recommended_action":"none","reason":"ok"}')
    with tempfile.TemporaryDirectory() as td:
        rep = Reporter(journal_path=Path(td) / "j.jsonl", project_id="drive")
        sup = Supervisor(client, rep, session_id="s1",
                         meta_enabled=True, meta_model="m")
        rep.ingest(kind="node_done", node="implement")   # not a fire
        rep.ingest(kind="worker", event_type="session.idle")  # not a fire
        sup._meta_review_fires()
        assert client.calls == 0
