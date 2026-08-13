"""Tests for the opencode client's ask_and_get_text polling."""

import json

import pytest

from regime_driver.infra.opencode import Message, OpenCodeClient, OpenCodeError


class _FakeSSEResponse:
    """Fake urllib response that iterates SSE-formatted lines."""

    def __init__(self, text: str):
        self._lines = [(line + "\n").encode() for line in text.split("\n")]
        self._i = 0
        self.closed = False

    def __iter__(self):
        return self

    def __next__(self):
        if self._i >= len(self._lines):
            raise StopIteration
        line = self._lines[self._i]
        self._i += 1
        return line

    def close(self):
        self.closed = True


def test_event_stream_parses_sse(monkeypatch):
    import urllib.request
    from regime_driver.infra.opencode import OpenCodeClient

    sse = (
        "event: server.connected\ndata: {\"healthy\":true}\n\n"
        "event: session.idle\ndata: {\"sessionID\":\"s1\"}\n\n"
    )
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, **kw: _FakeSSEResponse(sse))
    c = OpenCodeClient("http://x:4097")
    events = list(c.event_stream())
    assert events[0] == {"event": "server.connected", "data": {"healthy": True}}
    assert events[1] == {"event": "session.idle", "data": {"sessionID": "s1"}}


def test_event_stream_falls_back_to_data_type(monkeypatch):
    """Regression: opencode 1.18.11 emits the event type inside the `data`
    JSON (`{"type": "message.part.delta", ...}`) with NO SSE `event:` line. The
    stream must still surface the real event type, otherwise supervisor T2
    liveness and reporter delta-drop both silently see None (the 2026-08-13
    quality-run failure mode: journal flooded with 90% delta noise and long
    generations misjudged as stalled)."""
    import urllib.request
    from regime_driver.infra.opencode import OpenCodeClient

    sse = (
        "data: {\"type\": \"server.connected\", \"properties\": {}}\n\n"
        "data: {\"type\": \"message.part.delta\", \"properties\": {}}\n\n"
        "data: {\"type\": \"session.idle\", \"properties\": {\"sessionID\": \"s1\"}}\n\n"
    )
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, **kw: _FakeSSEResponse(sse))
    c = OpenCodeClient("http://x:4097")
    events = list(c.event_stream())
    assert [e["event"] for e in events] == [
        "server.connected", "message.part.delta", "session.idle"]
    assert events[2]["data"]["properties"]["sessionID"] == "s1"


class _FailingIter:
    """An iterator that raises partway through (simulates a dropped SSE stream)."""

    def __init__(self, lines, fail_after):
        self._lines = lines
        self._fail_after = fail_after
        self._i = 0

    def __iter__(self):
        return self

    def __next__(self):
        if self._i >= self._fail_after:
            raise OSError("stream dropped")
        if self._i >= len(self._lines):
            raise StopIteration
        line = self._lines[self._i]
        self._i += 1
        return line.encode()

    def close(self):
        pass


def test_event_stream_reconnects_after_drop(monkeypatch):
    import urllib.request
    from regime_driver.infra.opencode import OpenCodeClient

    calls = {"n": 0}
    good = "event: server.connected\ndata: {\"healthy\":true}\n\nevent: session.idle\ndata: {\"s\":\"1\"}\n\n"

    def fake_urlopen(req, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            # first connection drops after the server.connected event
            return _FailingIter(good.split("\n")[:3], fail_after=3)
        return _FakeSSEResponse("event: session.status\ndata: {\"s\":\"2\"}\n\n")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    c = OpenCodeClient("http://x:4097")
    ev = list(c.event_stream(reconnect=True, max_retries=3, backoff_sec=0.0))
    assert calls["n"] >= 2  # reconnected
    assert ev[0]["event"] == "server.connected"
    # the reconnected stream's events appear
    assert ev[-1]["event"] == "session.status"


def test_event_stream_no_reconnect_propagates(monkeypatch):
    import urllib.request
    from regime_driver.infra.opencode import OpenCodeClient, OpenCodeError

    def fake_urlopen(req, **kw):
        raise OSError("down")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    c = OpenCodeClient("http://x:4097")
    with pytest.raises(OpenCodeError):
        list(c.event_stream(reconnect=False))


def test_event_stream_first_is_connected(monkeypatch):
    import urllib.request
    from regime_driver.infra.opencode import OpenCodeClient

    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, **kw: _FakeSSEResponse(
                            "event: server.connected\ndata: {}\n\n"))
    c = OpenCodeClient("http://x:4097")
    assert list(c.event_stream())[0]["event"] == "server.connected"


def test_open_code_client_surface_is_lean():
    """Guard against dead API creeping back (see tests/test_deadcode.py)."""
    # only methods actually consumed by the driver/supervisor remain on the client
    for m in ("create_session", "session_status", "session_status_map", "list_sessions",
              "session_tokens", "abort_session", "delete_session", "send_message",
              "ask_and_get_text", "read_messages", "event_stream", "health"):
        assert hasattr(OpenCodeClient, m)
    for m in ("prompt_async", "todo", "children", "fork", "summarize"):
        assert not hasattr(OpenCodeClient, m)


def _raw(m: Message) -> dict:
    return {"info": {"role": m.role, "id": m.id}, "parts": [{"type": "text", "text": m.text}]}


class FakeClient(OpenCodeClient):
    """OpenCodeClient whose read_messages is scripted by the test."""

    def __init__(self, script):
        super().__init__("http://x:4097", timeout=5.0)
        self._script = list(script)  # list of new-message lists read per poll
        self.posted = 0

    def _request(self, method, path, body=None, timeout=None):
        if method == "POST" and "/message" in path:
            self.posted += 1
            return {}
        return {}

    def read_messages(self, session_id):
        if self._script:
            return self._script.pop(0)
        return []


def test_returns_new_message():
    # script[0] is the POST-pre state (empty); script[1] is the new reply
    c = FakeClient([
        [],
        [Message(id="m1", role="assistant", text="WORKER_OK")],
    ])
    assert c.ask_and_get_text("s1", "p", "reviewer") == "WORKER_OK"
    assert c.posted == 1


def test_waits_for_non_empty():
    # first poll: no new message (same count), then empty, then content
    c = FakeClient([
        [],
        [Message(id="m1", role="assistant", text="")],
        [Message(id="m1", role="assistant", text="WORKER_OK")],
    ])
    assert c.ask_and_get_text("s1", "p", "reviewer") == "WORKER_OK"


def test_raises_on_error_message():
    m = Message(id="m1", role="assistant", text="", error="provider failure")
    c = FakeClient([[m]])
    with pytest.raises(OpenCodeError):
        c.ask_and_get_text("s1", "p", "reviewer")


def test_timeout_when_no_new_message():
    c = FakeClient([])  # never any message
    with pytest.raises(OpenCodeError):
        c.ask_and_get_text("s1", "p", "reviewer")


def test_list_sessions_parses_response():
    c = FakeClient([])
    c._list = [{"id": "s1", "title": "t", "agent": "developer",
                "tokens": {"input": 10, "output": 2}}, "not-a-dict"]
    c.read_messages = lambda sid: []  # unused here
    c._request = lambda *a, **k: c._list
    sessions = c.list_sessions()
    assert len(sessions) == 1                  # non-dict entries dropped
    assert sessions[0]["id"] == "s1"