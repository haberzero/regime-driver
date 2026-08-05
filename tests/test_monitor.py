"""Tests for the safety monitor and repetition detection."""

import json
import time

import pytest

from regime_driver.app.monitor import Monitor, MonitorEvent, MonitorProbe
from regime_driver.core.repetition import RepetitionDetector, tokenize
from regime_driver.infra.settings import Settings


# --- repetition detection ---------------------------------------------------

def test_tokenize_cjk_and_ascii():
    toks = tokenize("设计一个系统 system design")
    assert "设" in toks
    assert "system" in toks
    assert "design" in toks


def test_repetition_detects_loop():
    d = RepetitionDetector()
    text = "重复重复重复重复重复重复重复重复重复重复重复重复重复重复重复"
    res = d.check(text)
    assert res.repeated


def test_repetition_clean_text():
    d = RepetitionDetector()
    text = "这是一个正常的很长的句子，它包含许多不同的词语和不同的表达方式，没有明显重复。"
    res = d.check(text)
    assert not res.repeated


def test_repetition_adjacent_echo():
    d = RepetitionDetector(adjacency_threshold=0.8)
    text = "hello world foo bar " * 40
    res = d.check(text)
    assert res.repeated


def test_repetition_short_text():
    d = RepetitionDetector()
    res = d.check("short")
    assert not res.repeated


def test_repetition_cjk_with_punctuation():
    """CJK punctuation must not collapse the window into one token."""
    d = RepetitionDetector()
    text = "我们需要进一步分析。我们需要进一步分析。我们需要进一步分析。我们需要进一步分析。我们需要进一步分析。我们需要进一步分析。我们需要进一步分析。我们需要进一步分析。我们需要进一步分析。我们需要进一步分析。"
    res = d.check(text)
    assert res.repeated


def test_clean_cjk_with_punctuation_not_flagged():
    d = RepetitionDetector()
    text = ("首先我们分析系统的架构设计，然后评估各个模块的职责划分，接着验证接口的一致性，"
            "最后检查边界条件与异常处理。每个步骤都需要仔细确认，确保方案可行且无隐患。")
    res = d.check(text)
    assert not res.repeated


# --- monitor detection ------------------------------------------------------

def make_monitor(stall_sec=10, on_stall="abort"):
    settings = Settings(
        monitor_enabled=True,
        monitor_poll_sec=0.1,
        stall_sec=stall_sec,
        on_stall=on_stall,
    )
    return settings


def test_monitor_detects_stall():
    """A busy session with no output growth for stall_sec -> stall event."""
    events = []
    settings = make_monitor(stall_sec=2)

    class FakeClient:
        def session_status(self, sid): return "busy"
        def session_tokens(self, sid): return (0, 100)
        def read_messages(self, sid): return []
        def abort_session(self, sid): pass

    m = Monitor(settings, FakeClient(), lambda: ["s1"], events.append)
    # simulate: first poll records output=100, then no growth
    probe = MonitorProbe("s1", "busy", 0, 100, "")
    assert m._detect("s1", probe) is None  # no stall yet
    # simulate no growth for 3s
    probe2 = MonitorProbe("s1", "busy", 0, 100, "")
    m._last_output["s1"] = 100
    m._stall_since["s1"] = time.time() - 3
    ev = m._detect("s1", probe2)
    assert ev is not None
    assert ev.kind == "stall"


def test_monitor_detects_dead_loop():
    """Latest text with repetition -> dead_loop event."""
    events = []
    settings = make_monitor()
    d = RepetitionDetector()

    class FakeClient:
        def session_status(self, sid): return "busy"
        def session_tokens(self, sid): return (50, 50)
        def read_messages(self, sid): return []
        def abort_session(self, sid): pass

    m = Monitor(settings, FakeClient(), lambda: ["s1"], events.append, repetition=d)
    probe = MonitorProbe("s1", "busy", 50, 50,
                         "重复重复重复重复重复重复重复重复重复重复重复")
    ev = m._detect("s1", probe)
    assert ev is not None
    assert ev.kind == "dead_loop"


def test_monitor_healthy_no_event():
    settings = make_monitor(stall_sec=2)
    d = RepetitionDetector()

    class FakeClient:
        def session_status(self, sid): return "busy"
        def session_tokens(self, sid): return (0, 100)
        def read_messages(self, sid): return []
        def abort_session(self, sid): pass

    m = Monitor(settings, FakeClient(), lambda: ["s1"], lambda e: None, repetition=d)
    probe = MonitorProbe("s1", "busy", 0, 100, "正常文本没有重复")
    assert m._detect("s1", probe) is None


def test_monitor_not_busy_resets_stall():
    settings = make_monitor(stall_sec=2)
    m = Monitor(settings, FakeClientStub(), lambda: ["s1"], lambda e: None)
    # same output but not busy -> idle -> reset stall tracking
    m._last_output["s1"] = 100
    m._stall_since["s1"] = time.time() - 3
    probe = MonitorProbe("s1", "idle", 0, 100, "")
    assert m._detect("s1", probe) is None
    assert "s1" not in m._stall_since


class FakeClientStub:
    def session_status(self, sid): return "idle"
    def session_tokens(self, sid): return (0, 120)
    def read_messages(self, sid): return []
    def abort_session(self, sid): pass


def test_monitor_poll_loop_calls_handler():
    """End-to-end: handler invoked on a stall via the poll loop."""
    settings = make_monitor(stall_sec=1)
    events = []

    class FakeClient:
        def __init__(self):
            self.calls = 0
        def session_status(self, sid): return "busy"
        def session_tokens(self, sid):
            self.calls += 1
            return (0, 100 if self.calls < 3 else 100)  # never grows
        def read_messages(self, sid): return []
        def abort_session(self, sid): pass

    m = Monitor(settings, FakeClient(), lambda: ["s1"], events.append)
    import time as _t
    m._last_output["s1"] = 100
    m._stall_since["s1"] = _t.time() - 3
    m._poll_once()
    assert len(events) == 1
    assert events[0].kind == "stall"


# --- driver on_stall dispatch (non-meta path) -------------------------------

def test_on_stall_report_user_does_not_abort():
    """on_stall=report_user sets the stop flag but does NOT abort the session."""
    from regime_driver.app.driver import RegimeDriver
    from regime_driver.app.monitor import MonitorEvent
    from regime_driver.core.state_machine import StateMachine
    from regime_driver.infra.settings import Settings
    from regime_driver.infra.regime_loader import load_regime

    aborted = []

    class FakeClient:
        def abort_session(self, sid): aborted.append(sid)
        def create_session(self, t): return "x"
        def read_messages(self, sid): return []
        def session_status(self, sid): return "busy"
        def session_tokens(self, sid): return (0, 100)

    sm = load_regime()
    settings = Settings(on_stall="report_user", meta_analyze_enabled=False,
                        monitor_enabled=False)
    d = RegimeDriver(settings, sm, FakeClient())
    d._current_node = "design"
    ev = MonitorEvent("stall", "s1", "stalled")
    d._on_monitor_event(ev)
    assert d._monitor_stop == "stall"  # flagged
    assert aborted == []  # NOT aborted


def test_on_stall_none_does_nothing():
    from regime_driver.app.driver import RegimeDriver
    from regime_driver.app.monitor import MonitorEvent
    from regime_driver.infra.settings import Settings
    from regime_driver.infra.regime_loader import load_regime

    aborted = []

    class FakeClient:
        def abort_session(self, sid): aborted.append(sid)
        def create_session(self, t): return "x"
        def read_messages(self, sid): return []
        def session_status(self, sid): return "busy"
        def session_tokens(self, sid): return (0, 100)

    sm = load_regime()
    settings = Settings(on_stall="none", meta_analyze_enabled=False, monitor_enabled=False)
    d = RegimeDriver(settings, sm, FakeClient())
    d._on_monitor_event(MonitorEvent("stall", "s1", "stalled"))
    assert d._monitor_stop is None
    assert aborted == []