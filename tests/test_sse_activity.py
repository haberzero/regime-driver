"""Tests for the SSE-activity tracker (WORK_PLAN10).

SseActivity is the liveness linchpin: the in-process watchdog and the external
supervisor both decide "is this busy session actually alive?" from the activity
timestamps it records from the SSE `/event` stream. These tests pin the real
payload parsing (sessionID inside `properties`), the server.connected/heartbeat
exclusion, and the drop/reconnect backoff path — the exact things a regression
would silently break and re-create the long-thinking false-kill.
"""

from __future__ import annotations

import time

from regime_driver.app.sse_activity import SseActivity, is_progress_event
from regime_driver.infra.opencode import OpenCodeClient


class ScriptedClient:
    """A minimal OpenCodeClient-compatible fake yielding scripted SSE events."""

    def __init__(self, events, *, drop_on_connect=None):
        self.events = list(events)
        self.drop_on_connect = drop_on_connect  # raise during the Nth connection
        self.connect_calls = 0
        self.yielded = 0

    def event_stream(self, reconnect=False, max_retries=None):
        while True:
            self.connect_calls += 1
            if self.drop_on_connect and self.connect_calls == self.drop_on_connect:
                raise RuntimeError("simulated SSE drop on connect")
            for ev in self.events:
                self.yielded += 1
                yield ev
            return  # clean end -> caller reconnects


def _delta(sid, t=None):
    # mirror OpenCodeClient.event_stream's normalized shape: the event type is
    # surfaced in the `event` field (fallback from data.type), and the sessionID
    # lives inside data.properties.
    return {"event": "message.part.delta",
            "data": {"type": "message.part.delta",
                     "properties": {"sessionID": sid}}}


def _heartbeat():
    return {"event": "server.heartbeat", "data": {}}


def _connected():
    return {"event": "server.connected", "data": {}}


def test_is_progress_event_classification():
    # server.connected / heartbeat must NOT count (would make a dead session
    # look alive forever); message.* / session.* are genuine progress.
    assert is_progress_event("server.connected") is False
    assert is_progress_event("server.heartbeat") is False
    assert is_progress_event(None) is False
    assert is_progress_event("message.part.delta") is True
    assert is_progress_event("message.part.updated") is True
    assert is_progress_event("message.completed") is True
    assert is_progress_event("session.idle") is True
    assert is_progress_event("session.status") is True


def test_records_activity_for_real_payload_shape():
    # opencode v1.18.11 SSE blocks are {id, type, properties} with sessionID
    # inside `properties` (handlers/event.ts + session-svc.ts). The tracker must
    # parse that exact shape.
    client = ScriptedClient([_connected(), _delta("s1")])
    tr = SseActivity(client, start=True)
    try:
        deadline = time.time() + 3.0
        while tr.last_activity("s1") == 0.0 and time.time() < deadline:
            time.sleep(0.02)
        assert tr.last_activity("s1") > 0.0, "must record activity for session s1"
        assert tr.last_activity("s2") == 0.0, "unrelated session must stay 0"
    finally:
        tr.stop()


def test_heartbeat_does_not_record_activity():
    client = ScriptedClient([_connected(), _heartbeat(), _heartbeat()])
    tr = SseActivity(client, start=True)
    try:
        time.sleep(0.3)
        # no message/session events at all -> no activity for any session
        assert tr.last_activity("s1") == 0.0
    finally:
        tr.stop()


def test_reconnects_after_clean_stream_end():
    # a clean stream end (generator return) must not kill the tracker; it
    # reconnects and keeps recording activity.
    events = [_connected(), _delta("s1")]
    client = ScriptedClient(events)
    tr = SseActivity(client, start=True)
    try:
        deadline = time.time() + 3.0
        while client.connect_calls < 2 and time.time() < deadline:
            time.sleep(0.02)
        # after a reconnect, activity still flows
        deadline = time.time() + 3.0
        while tr.last_activity("s1") == 0.0 and time.time() < deadline:
            time.sleep(0.02)
        assert client.connect_calls >= 2, "must reconnect after clean stream end"
        assert tr.last_activity("s1") > 0.0
    finally:
        tr.stop()


def test_survives_transient_drop_and_recovers():
    # a connect drop must not kill the tracker; it backs off and reconnects.
    client = ScriptedClient([_connected(), _delta("s1")], drop_on_connect=1)
    tr = SseActivity(client, start=True)
    try:
        deadline = time.time() + 4.0
        while tr.last_activity("s1") == 0.0 and time.time() < deadline:
            time.sleep(0.05)
        assert tr.last_activity("s1") > 0.0, "must recover after a drop"
        assert client.connect_calls >= 2, "must have reconnected after the drop"
    finally:
        tr.stop()


def test_multi_session_tracked_independently():
    client = ScriptedClient([_connected(), _delta("a"), _delta("b"), _delta("a")])
    tr = SseActivity(client, start=True)
    try:
        deadline = time.time() + 3.0
        while (tr.last_activity("a") == 0.0 or tr.last_activity("b") == 0.0) \
                and time.time() < deadline:
            time.sleep(0.02)
        assert tr.last_activity("a") > 0.0
        assert tr.last_activity("b") > 0.0
    finally:
        tr.stop()


def test_stop_is_idempotent():
    tr = SseActivity(ScriptedClient([_connected()]), start=True)
    tr.stop()
    tr.stop()  # second stop must not raise
    assert tr._thread is None


def test_is_alive_and_last_activity():
    client = ScriptedClient([_delta("s1")])
    tr = SseActivity(client, start=True)
    try:
        deadline = time.time() + 3.0
        while tr.last_activity("s1") == 0.0 and time.time() < deadline:
            time.sleep(0.02)
        assert tr.is_alive("s1", within_sec=60) is True
        assert tr.is_alive("missing", within_sec=60) is False
    finally:
        tr.stop()
