"""Independent safety monitor (app layer): a background thread that watches all
managed sessions for stalls, dead loops, and API hangs.

This is deliberately independent of the main flow: it runs on its own thread and
polls the worker's live session state (token counts, latest message text,
busy/idle status) at a fixed cadence. It does NOT wait for the main flow to be
idle — it can interrupt a long-running turn (e.g. a model stuck in a thinking
loop or a hung API request) that the main flow cannot detect on its own.

On detecting a problem it invokes a configured handler (e.g. abort + escalate to
human). This is the "human pressing ESC repeatedly" equivalent: an authoritative
emergency stop that works even when the in-process logic is stuck.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

from ..core.json_utils import latest_assistant_text
from ..core.repetition import RepetitionDetector
from ..infra.opencode import OpenCodeClient
from ..infra.settings import Settings


@dataclass
class MonitorProbe:
    """Snapshot of a session's monitored state at one poll."""

    session_id: str
    status: str | None
    reasoning: int
    output: int
    latest_text: str  # latest assistant message text (for repetition check)


@dataclass
class MonitorEvent:
    """A problem the monitor detected, for the handler to act on."""

    kind: str  # "stall" | "dead_loop"
    session_id: str
    detail: str


Handler = Callable[[MonitorEvent], None]


class Monitor:
    """Background thread that polls sessions and reports problems.

    Args:
        settings: driver settings (poll cadence, thresholds, on_stall action).
        client: opencode client.
        session_provider: callable returning the list of session ids to watch.
        handler: callable invoked with a MonitorEvent when a problem is found.
        repetition: optional RepetitionDetector (injectable for tests).
    """

    def __init__(
        self,
        settings: Settings,
        client: OpenCodeClient,
        session_provider: Callable[[], list[str]],
        handler: Handler,
        repetition: RepetitionDetector | None = None,
    ) -> None:
        self.settings = settings
        self.client = client
        self.session_provider = session_provider
        self.handler = handler
        self.repetition = repetition or RepetitionDetector()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_output: dict[str, int] = {}
        self._stall_since: dict[str, float] = {}
        self._stall_fired: set[str] = set()
        self._dead_loop_fired: set[str] = set()

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="regime-monitor")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    # -- main loop ----------------------------------------------------------

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._poll_once()
            except Exception:
                # never let a poll error kill the monitor
                pass
            self._stop.wait(self.settings.monitor_poll_sec)

    def _poll_once(self) -> None:
        for sid in self.session_provider():
            probe = self._probe(sid)
            if probe is None:
                continue
            event = self._detect(sid, probe)
            if event is not None:
                try:
                    self.handler(event)
                except Exception:
                    pass

    # -- probing ------------------------------------------------------------

    def _probe(self, session_id: str) -> MonitorProbe | None:
        try:
            status = self.client.session_status(session_id)
            reasoning, output = self.client.session_tokens(session_id)
        except Exception:
            return None
        latest_text = ""
        try:
            messages = self.client.read_messages(session_id)
            latest_text = latest_assistant_text(messages)
        except Exception:
            pass
        return MonitorProbe(
            session_id=session_id,
            status=status,
            reasoning=reasoning,
            output=output,
            latest_text=latest_text,
        )

    # -- detection ----------------------------------------------------------

    def _detect(self, session_id: str, probe: MonitorProbe) -> MonitorEvent | None:
        """Classify a probe. Returns a MonitorEvent or None (healthy)."""
        # 1. dead loop: latest text shows loop-style repetition (fire once until text changes)
        if probe.latest_text:
            res = self.repetition.check(probe.latest_text)
            if res.repeated:
                if session_id not in self._dead_loop_fired:
                    self._dead_loop_fired.add(session_id)
                    return MonitorEvent("dead_loop", session_id, f"repetition detected: {res.reason}")
            else:
                self._dead_loop_fired.discard(session_id)

        # 2. stall: busy but no token/output growth for stall_sec
        output = probe.output
        prev = self._last_output.get(session_id)
        if prev is not None and output == prev:
            if probe.status == "busy":
                since = self._stall_since.setdefault(session_id, time.time())
                if time.time() - since >= self.settings.stall_sec:
                    if session_id not in self._stall_fired:
                        self._stall_fired.add(session_id)
                        return MonitorEvent(
                            "stall",
                            session_id,
                            f"busy but no output growth for {self.settings.stall_sec}s",
                        )
            else:
                # not busy and no growth -> healthy/idle, reset
                self._stall_since.pop(session_id, None)
                self._stall_fired.discard(session_id)
        else:
            self._last_output[session_id] = output
            self._stall_since.pop(session_id, None)
            self._stall_fired.discard(session_id)
        return None