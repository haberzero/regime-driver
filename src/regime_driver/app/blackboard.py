"""Thread-safe shared blackboard (app layer).

    A simple key/value store shared across statechart units, with optional change
    notification. This addresses the "global variable / shared state" gap: units can
    publish runtime metrics (current node, phase, budget, counters) to a central
    place that other units (the constitution, the god dialog) can read and
    subscribe to changes.

Thread safety: all access is guarded by a reentrant lock, so the workflow thread
(writer) and the constitution/observer threads (readers) can share it safely.
"""

from __future__ import annotations

import threading
import time
from typing import Callable

# event names emitted on the bus when the blackboard changes
CHANGED_EVENT = "blackboard.changed"

# workflow metrics keys that form a per-workflow status view (single source of
# truth shared by the god dialog and the report bus)
WORKFLOW_METRICS = ("node", "phase", "node_count", "state", "heartbeat",
                    "start_time", "wait_sid", "waiting_s")


def workflow_status(bb: "Blackboard") -> dict[str, dict]:
    """Derive a per-workflow status map from a blackboard's metric keys.

    Keys are `{workflow_id}.{metric}` (multi-workflow isolation on a shared
    blackboard). Only `WORKFLOW_METRICS` keys are surfaced. Shared by the
    GodDialog/report so the view logic lives in exactly one place.
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


# human-readable labels for the status view (readability, shared by god dialog/report)
STATE_LABELS = {"running": "运行中", "done": "完成", "aborted": "中止",
                "error": "错误", "idle": "空闲", "blocked": "阻塞"}
PHASE_LABELS = {"agent_wait": "待执行", "judge_wait": "待审查", "none": "-"}


def status_line(wid: str, s: dict, now: float | None = None) -> str:
    """Render one workflow's status as a human-readable line."""
    now = now or time.time()
    hb = s.get("heartbeat") or 0
    age = f"{now - float(hb):.0f}s" if hb else "n/a"
    state = (s.get("state") or "idle").lower()
    phase_raw = s.get("phase")
    phase = PHASE_LABELS.get(phase_raw, phase_raw or "-")
    wait = s.get("waiting_s")
    wait_s = f" 已等{wait:.0f}s" if isinstance(wait, (int, float)) else ""
    node = s.get("node") or "-"
    return (f"{wid}: {STATE_LABELS.get(state, state)} @ {node} "
            f"[{phase}]{wait_s} 心跳{age} 节点数{s.get('node_count', 0)}")


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