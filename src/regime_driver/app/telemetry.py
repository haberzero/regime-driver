"""Telemetry / visualization (app layer).

A StatechartUnit that subscribes to `watchdog_fire` and `blackboard.changed`
events and to the workflow metrics, so a human or tool can observe a live run.
This is the "visualization" surface built on the pub/sub + blackboard mechanisms:
it never asks for state; it is *pushed* events and *reads* the blackboard.

`render()` produces a human-readable status table over the workflows.
"""

from __future__ import annotations

import time
from collections import deque

from ..core.statechart import StatechartUnit


class Telemetry(StatechartUnit):
    """Collects watchdog/blackboard events and renders a live status snapshot."""

    def __init__(self, unit_id: str = "telemetry", bus=None, max_events: int = 200) -> None:
        super().__init__(unit_id, bus)
        self.max_events = max_events
        self.events: deque = deque(maxlen=max_events)
        self.on_event("watchdog_fire", self._on_watchdog)
        self.on_event("blackboard.changed", self._on_blackboard)
        if bus is not None:
            self.subscribe("watchdog_fire")
            self.subscribe("blackboard.changed")

    # -- event intake --------------------------------------------------------

    def _on_watchdog(self, payload: dict) -> None:
        self.events.append(("watchdog_fire", time.time(), payload))

    def _on_blackboard(self, payload: dict) -> None:
        self.events.append(("blackboard.changed", time.time(), payload))

    # -- snapshot ------------------------------------------------------------

    def workflow_status(self) -> dict[str, dict]:
        """Read the blackboard and return per-workflow status."""
        bb = self.bus.blackboard if self.bus is not None else None
        if bb is None:
            return {}
        workflows: dict[str, dict] = {}
        for key in bb.keys():
            if "." not in key:
                continue
            wid, _, metric = key.rpartition(".")
            if metric not in ("node", "phase", "node_count", "state", "heartbeat", "start_time"):
                continue
            workflows.setdefault(wid, {})[metric] = bb.get(key)
        return workflows

    def recent_watchdog(self, limit: int = 10) -> list[dict]:
        return [e[2] for e in self.events if e[0] == "watchdog_fire"][-limit:]

    # -- rendering -----------------------------------------------------------

    def render(self) -> str:
        lines = ["=== workflow status ==="]
        status = self.workflow_status()
        if not status:
            lines.append("(no workflows reported yet)")
        for wid in sorted(status):
            s = status[wid]
            hb = s.get("heartbeat") or 0
            age = f"{time.time() - float(hb):.0f}s ago" if hb else "n/a"
            lines.append(
                f"  {wid}: state={s.get('state')} node={s.get('node')} "
                f"phase={s.get('phase')} nodes={s.get('node_count')} hb={age}"
            )
        lines.append("=== recent watchdog_fire ===")
        wd = self.recent_watchdog()
        if not wd:
            lines.append("  (none)")
        for _, ts, p in wd:
            lines.append(
                f"  {time.strftime('%H:%M:%S', time.localtime(ts))} "
                f"kind={p.get('kind')} session={p.get('session')} "
                f"detail={p.get('detail')}"
            )
        lines.append(f"=== event buffer ===")
        lines.append(f"  {len(self.events)} events captured")
        return "\n".join(lines)