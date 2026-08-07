"""Thread-safe shared blackboard (app layer).

A simple key/value store shared across statechart units, with optional change
notification. This addresses the "global variable / shared state" gap: units can
publish runtime metrics (current node, phase, budget, counters) to a central
place that other units (the constitution, a telemetry observer) can read and
subscribe to changes.

Thread safety: all access is guarded by a reentrant lock, so the workflow thread
(writer) and the constitution/observer threads (readers) can share it safely.
"""

from __future__ import annotations

import threading
from typing import Callable

# event names emitted on the bus when the blackboard changes
CHANGED_EVENT = "blackboard.changed"

# workflow metrics keys that form a per-workflow status view (single source of
# truth shared by telemetry and the god dialog)
WORKFLOW_METRICS = ("node", "phase", "node_count", "state", "heartbeat",
                    "start_time", "wait_sid", "waiting_s")


def workflow_status(bb: "Blackboard") -> dict[str, dict]:
    """Derive a per-workflow status map from a blackboard's metric keys.

    Keys are `{workflow_id}.{metric}` (multi-workflow isolation on a shared
    blackboard). Only `WORKFLOW_METRICS` keys are surfaced. Shared by
    Telemetry/GodDialog so the view logic lives in exactly one place.
    """
    out: dict[str, dict] = {}
    if bb is None:
        return out
    for key in bb.keys():
        if "." not in key:
            continue
        wid, _, metric = key.rpartition(".")
        if metric not in WORKFLOW_METRICS:
            continue
        out.setdefault(wid, {})[metric] = bb.get(key)
    return out


class Blackboard:
    """A lock-protected shared key/value store with optional change events."""

    def __init__(self, publisher: Callable[[str, dict], None] | None = None) -> None:
        self._store: dict = {}
        self._lock = threading.RLock()
        # publisher(event_name, fields) called on every change (wired to the bus)
        self.publisher = publisher

    # -- reads ---------------------------------------------------------------

    def get(self, key: str, default=None):
        with self._lock:
            return self._store.get(key, default)

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._store)

    def keys(self) -> list:
        with self._lock:
            return list(self._store)

    def __contains__(self, key: str) -> bool:
        with self._lock:
            return key in self._store

    # -- writes --------------------------------------------------------------

    def set(self, key: str, value) -> None:
        with self._lock:
            self._store[key] = value
        self._notify(key, value)

    def update(self, **kv) -> None:
        with self._lock:
            self._store.update(kv)
        for key, value in kv.items():
            self._notify(key, value)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)
        self._notify(key, None)

    def _notify(self, key: str, value) -> None:
        if self.publisher is not None:
            try:
                self.publisher(CHANGED_EVENT, {"key": key, "value": value})
            except Exception:
                # a subscriber error must never break the writer
                pass