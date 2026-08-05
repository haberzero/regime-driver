"""[WORK_DONE] segment protocol parser (pure domain logic).

The developer ends each segment with a standalone `[WORK_DONE]` marker line
followed by (or preceded by) a structured report. This module parses the
marker and extracts the report.
"""

from __future__ import annotations

import re

from .models import DEFAULT_WORK_DONE_MARKER, SegmentReport


class SegmentParser:
    """Parses developer messages for the [WORK_DONE] segment boundary."""

    def __init__(self, marker: str = DEFAULT_WORK_DONE_MARKER) -> None:
        self.marker = marker
        self._re = re.compile(rf"(?m)^\s*{re.escape(marker)}\s*$")

    def find_marker(self, text: str | None) -> int:
        """Return the index of the marker line, or -1 if not found.

        The marker must be on its own line (not inline in prose).
        """
        if not text:
            return -1
        m = self._re.search(text)
        return m.start() if m else -1

    def has_segment_end(self, text: str | None) -> bool:
        return self.find_marker(text) >= 0

    def extract_report(self, text: str | None) -> str | None:
        """Return the text before the marker, or None if no marker."""
        idx = self.find_marker(text)
        if idx < 0:
            return None
        return text[:idx].strip() or None

    def parse(self, text: str | None) -> SegmentReport | None:
        """Parse the report into a structured SegmentReport (best-effort).

        Returns None if no marker present. Field extraction is lenient:
        missing fields are left empty rather than raising.
        """
        report = self.extract_report(text)
        if report is None:
            return None
        return _parse_report_block(report)


def _parse_report_block(report: str) -> SegmentReport:
    """Leniently parse the report block into structured fields.

    Recognizes lines like:
      - 文件: foo.py, bar.py
      - 测试命令: python -m pytest
      - 测试结果: 3 passed
      - 技术债: ...
      - 待决点: ...
    Unknown/absent fields are left empty.
    """
    files: list[str] = []
    test_command: str | None = None
    test_result: str | None = None
    tech_debt: list[str] = []
    open_questions: list[str] = []

    for line in report.splitlines():
        line = line.strip().lstrip("-").strip()
        if not line:
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if key in ("文件", "files", "改动文件", "文件改动"):
            files = [f.strip() for f in re.split(r"[,，、]", value) if f.strip()]
        elif key in ("测试命令", "test_command", "测试"):
            test_command = value or None
        elif key in ("测试结果", "test_result", "结果"):
            test_result = value or None
        elif key in ("技术债", "tech_debt", "技术债务"):
            tech_debt = [f.strip() for f in re.split(r"[,，、]", value) if f.strip()]
        elif key in ("待决点", "open_questions", "待决", "待决问题"):
            open_questions = [f.strip() for f in re.split(r"[,，、]", value) if f.strip()]

    return SegmentReport(
        files_changed=files,
        test_command=test_command,
        test_result=test_result,
        tech_debt=tech_debt,
        open_questions=open_questions,
    )