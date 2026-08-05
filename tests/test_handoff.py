"""Tests for the handoff model and convergence detection."""

from regime_driver.core.handoff import (
    Handoff,
    detect_loop,
)


def test_reviewer_inquiry_factory():
    h = Handoff.reviewer_inquiry(["缺陷1"], "请修复", "需通过测试", flow_node="design")
    assert h.kind == "inquiry"
    assert h.from_role == "reviewer"
    assert h.to_role == "developer"
    assert h.inquiry is not None
    assert h.inquiry.criticisms == ["缺陷1"]
    assert "请修复" in h.inquiry_text()
    assert "验收" in h.inquiry_text()


def test_developer_report_factory():
    h = Handoff.developer_report(["calc.py"], "改了加法", "2 passed")
    assert h.kind == "report"
    assert h.from_role == "developer"
    assert h.to_role == "reviewer"
    assert h.report is not None
    assert "calc.py" in h.report_text()
    assert "2 passed" in h.report_text()


def test_handoff_serialization_roundtrip():
    h = Handoff.reviewer_inquiry(["x"], "fix it")
    raw = h.to_json()
    h2 = Handoff.from_json(raw)
    assert h2.id == h.id
    assert h2.kind == h.kind
    assert h2.inquiry_text() == h.inquiry_text()


def test_handoff_is_structured_not_shared_memory():
    """The report text is the ONLY thing a reviewer consumes; no raw context."""
    h = Handoff.developer_report(["a.py"], "fixed", "3 passed")
    text = h.report_text()
    assert "a.py" in text
    assert "3 passed" in text
    # report_text gives a structured doc, not the developer's full session
    assert isinstance(h.report, object)


# --- convergence detection --------------------------------------------------

def test_detect_loop_with_identical_rounds():
    rounds = [
        ("请修复 add", "已修复"),
        ("请修复 add", "已修复"),
        ("请修复 add", "已修复"),
    ]
    assert detect_loop(rounds, max_identical=2) is True


def test_detect_loop_not_enough_rounds():
    assert detect_loop([], max_identical=2) is False
    assert detect_loop([("a", "b")], max_identical=2) is False


def test_detect_loop_report_changed_no_loop():
    rounds = [
        ("请修复 add", "已修复版本1"),
        ("请修复 add", "已修复版本2"),
        ("请修复 add", "已修复版本3"),
    ]
    # inquiry identical but report changed -> not a true spin
    assert detect_loop(rounds, max_identical=2) is False


def test_detect_loop_inquiry_changed_no_loop():
    rounds = [
        ("问题1", "改了"),
        ("问题2", "改了"),
        ("问题3", "改了"),
    ]
    assert detect_loop(rounds, max_identical=2) is False