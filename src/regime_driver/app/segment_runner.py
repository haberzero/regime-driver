"""Segment runner (app layer): drive one developer segment to completion.

Sends an instruction, polls the session for the [WORK_DONE] marker (or
timeout), and parses the structured report.
"""

from __future__ import annotations

import time
from dataclasses import dataclass

from ..core.segment import SegmentParser
from ..infra.opencode import Message, OpenCodeClient


@dataclass
class SegmentResult:
    """Outcome of a single developer segment."""

    outcome: str  # "complete" | "timeout" | "error"
    report: str | None = None
    detail: str | None = None


class SegmentRunner:
    """Runs one developer segment and waits for the [WORK_DONE] boundary."""

    def __init__(
        self,
        client: OpenCodeClient,
        parser: SegmentParser | None = None,
        poll_sec: float = 5.0,
    ) -> None:
        self.client = client
        self.parser = parser or SegmentParser()
        self.poll_sec = poll_sec

    def run(
        self,
        session_id: str,
        agent: str,
        instruction: str,
        deadline_sec: int,
        cancel_event: Callable[[], bool] | None = None,
    ) -> SegmentResult:
        """Send an instruction and poll until [WORK_DONE] or timeout.

        cancel_event: optional callable returning True to abort the poll early
        (used by the safety monitor to interrupt a stalled turn).
        """
        try:
            self.client.send_message(session_id, instruction, agent)
        except Exception as exc:  # OpenCodeError
            return SegmentResult(outcome="error", detail=str(exc))

        t0 = time.time()
        while time.time() - t0 < deadline_sec:
            if cancel_event is not None and cancel_event():
                return SegmentResult(outcome="cancelled", detail="monitor cancel")
            try:
                messages = self.client.read_messages(session_id)
            except Exception as exc:
                return SegmentResult(outcome="error", detail=str(exc))
            latest = self._latest_assistant(messages)
            if latest and self.parser.has_segment_end(latest):
                report = self.parser.extract_report(latest)
                return SegmentResult(outcome="complete", report=report)
            time.sleep(self.poll_sec)

        return SegmentResult(outcome="timeout")

    @staticmethod
    def _latest_assistant(messages: list[Message]) -> str | None:
        for m in reversed(messages):
            if m.role == "assistant":
                return m.text
        return None