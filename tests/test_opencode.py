"""Tests for the opencode client's ask_and_get_text polling."""

import pytest

from regime_driver.infra.opencode import Message, OpenCodeClient, OpenCodeError


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