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


def test_event_stream_first_is_connected(monkeypatch):
    import urllib.request
    from regime_driver.infra.opencode import OpenCodeClient

    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda req, **kw: _FakeSSEResponse(
                            "event: server.connected\ndata: {}\n\n"))
    c = OpenCodeClient("http://x:4097")
    assert list(c.event_stream())[0]["event"] == "server.connected"


def test_prompt_async_and_extras():
    calls = []

    class C(OpenCodeClient):
        def _request(self, method, path, body=None, timeout=None):
            calls.append((method, path, body))
            if "/todo" in path:
                return [{"id": "t1"}]
            if "/children" in path:
                return [{"id": "child1"}]
            if "/fork" in path:
                return {"id": "new-session"}
            if "/summarize" in path:
                return True
            return {}

    c = C("http://x:4097")
    c.prompt_async("s1", "hi", "developer")
    assert calls[-1] == ("POST", "/session/s1/prompt_async", {"agent": "developer",
                                                              "parts": [{"type": "text", "text": "hi"}]})
    assert c.todo("s1") == [{"id": "t1"}]
    assert c.children("s1") == [{"id": "child1"}]
    assert c.fork("s1") == "new-session"
    assert c.fork("s1", "m1") == "new-session"
    assert calls[-1][1] == "/session/s1/fork"
    assert c.summarize("s1") is True


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