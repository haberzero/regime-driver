"""SSE activity tracker — the single reliable liveness signal.

opencode's `session_tokens` are STEP-granular (the server persists them only at
`step-finish`, via an async projector; session.ts/processor.ts). During a long
single-step generation they stay 0 even while the model is streaming reasoning.
The ONLY immediate, reliable liveness signal is the SSE `/event` stream:
`message.part.delta` etc. are pushed continuously while a generation streams.

This tracker consumes that stream and maintains `{session_id: last_activity_ts}`
so any consumer (in-process watchdog via the workflow REPORT, or the external
supervisor) can decide "is this busy session actually alive?" from real opencode
observables instead of derived counters.

Design:
  * A single daemon thread keeps ONE `/event` subscription open for the client's
    lifetime and records the latest timestamp of any progress event
    (`message.*` / `session.*`, excluding the per-poll `server.connected` and the
    10s `server.heartbeat`).
  * Thread-safe: the map is written under a lock; reads are cheap snapshots.
  * MockClient parity: MockClient gains an `event_stream` that emits progress
    events for live sessions and stays silent for stalled ones — so offline
    runs (preflight/tests) exercise the exact same stall semantics.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

from ..infra.drive_client import DriveClient


def is_progress_event(event_type: str | None) -> bool:
    """True for SSE events that indicate genuine session progress.

    `server.connected` (per-connection handshake) and `server.heartbeat`
    (10s keepalive) must NOT count as activity or a dead session would look
    alive forever.
    """
    if not event_type:
        return False
    if event_type in ("server.connected", "server.heartbeat"):
        return False
    return event_type.startswith(("message.", "session."))


class SseActivity:
    """Tracks the last SSE-progress timestamp per session (thread-safe)."""

    def __init__(
        self,
        client: DriveClient,
        *,
        start: bool = True,
        max_retries: int | None = None,
        poll_sleep: float = 0.5,
    ) -> None:
        self._client = client
        self._max_retries = max_retries
        self._poll_sleep = poll_sleep
        self._last: dict[str, float] = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        if start:
            self.start()

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run, name="sse-activity", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=3.0)
            # only clear if the thread actually exited; otherwise a later
            # start() would spawn a duplicate connection while the old one is
            # still blocked on an SSE read (up to the next heartbeat).
            if not self._thread.is_alive():
                self._thread = None

    def _run(self) -> None:
        """Keep a live `/event` subscription; record progress timestamps."""
        retries = 0
        while not self._stop.is_set():
            try:
                for raw in self._client.event_stream(
                        reconnect=False, max_retries=0):
                    if self._stop.is_set():
                        return
                    etype = raw.get("event")
                    if not is_progress_event(etype):
                        continue
                    # the session is embedded in the event payload's properties
                    data = raw.get("data")
                    props = {}
                    if isinstance(data, dict):
                        props = data.get("properties") or {}
                    sid = props.get("sessionID") or props.get("session_id")
                    if sid:
                        now = time.time()
                        with self._lock:
                            self._last[sid] = now
            except Exception:
                # transient SSE failure: reconnect with backoff; never die.
                if self._max_retries is not None:
                    retries += 1
                    if retries > self._max_retries:
                        return
                # a dropped stream reconnects after a short backoff; honour stop.
                if self._stop.wait(self._poll_sleep + 1.0):
                    return
                continue
            retries = 0
            if self._stop.wait(self._poll_sleep):
                return

    # -- queries ------------------------------------------------------------

    def last_activity(self, session_id: str) -> float:
        """Wall-clock timestamp of the last SSE progress for a session (0=none)."""
        with self._lock:
            return self._last.get(session_id, 0.0)

    def is_alive(self, session_id: str, within_sec: float) -> bool:
        """True if the session had SSE progress within the last `within_sec`."""
        t = self.last_activity(session_id)
        return t > 0 and (time.time() - t) <= within_sec
