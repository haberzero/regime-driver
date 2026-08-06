"""E2E debug: run a real flow on the live worker with per-operation timing.

Wraps the real OpenCodeClient to time every send_message POST (streaming
generation) and read_messages / session_* call, then runs the real
StatechartDriver. Prints a per-node wall-time breakdown and the POST durations
per agent, so we can see WHERE a slow E2E goes:

  * large judge POST duration  -> hypothesis ① complex prompt long reasoning
  * large/accumulating read RTT -> hypothesis ③ read_messages blocking the loop

Usage: python ops/e2e_debug.py [--task "TASK"] [--timeout 900]
"""
from __future__ import annotations

import argparse
import re
import sys
import time

sys.path.insert(0, "/home/haber/oc-meta/src")

from regime_driver.app.statechart_driver import StatechartDriver
from regime_driver.infra.ledger import Ledger
from regime_driver.infra.opencode import Message, OpenCodeClient
from regime_driver.infra.regime_loader import load_regime
from regime_driver.infra.settings import Settings

_NODE_RE = re.compile(r"当前节点[:：]\s*(\w+)")


class TimingClient(OpenCodeClient):
    """OpenCodeClient that records the duration of every remote operation."""

    def __init__(self, base, model, timeout=900.0):
        super().__init__(base, model=model, timeout=timeout)
        self.ops: list[dict] = []

    def send_message(self, session_id, text, agent):
        node = _NODE_RE.search(text)
        nid = node.group(1) if node else "?"
        t0 = time.monotonic()
        try:
            super().send_message(session_id, text, agent)
        finally:
            self.ops.append({"kind": "send", "sid": session_id, "agent": agent,
                             "node": nid, "dur": round(time.monotonic() - t0, 2)})

    def read_messages(self, session_id):
        t0 = time.monotonic()
        try:
            return super().read_messages(session_id)
        finally:
            self.ops.append({"kind": "read", "sid": session_id,
                             "dur": round(time.monotonic() - t0, 2)})

    def session_status(self, session_id):
        t0 = time.monotonic()
        try:
            return super().session_status(session_id)
        finally:
            self.ops.append({"kind": "status", "sid": session_id,
                             "dur": round(time.monotonic() - t0, 2)})

    def session_tokens(self, session_id):
        t0 = time.monotonic()
        try:
            return super().session_tokens(session_id)
        finally:
            self.ops.append({"kind": "tokens", "sid": session_id,
                             "dur": round(time.monotonic() - t0, 2)})

    def abort_session(self, session_id):
        t0 = time.monotonic()
        try:
            super().abort_session(session_id)
        finally:
            self.ops.append({"kind": "abort", "sid": session_id,
                             "dur": round(time.monotonic() - t0, 2)})

    def create_session(self, title):
        t0 = time.monotonic()
        try:
            return super().create_session(title)
        finally:
            self.ops.append({"kind": "create", "dur": round(time.monotonic() - t0, 2)})


def summarize(ops: list[dict], task: str, outcome, end, detail, wall):
    print("\n=== E2E timing summary ===")
    print(f"task: {task}")
    print(f"outcome: {outcome}  end: {end}  detail: {detail}")
    print(f"total wall: {wall:.1f}s   ops: {len(ops)}")
    # per-node send (generation) durations, in order
    sends = [o for o in ops if o["kind"] == "send"]
    print(f"\n-- send_message POST (streaming generation) per call --")
    for o in sends:
        print(f"  {o['agent']:>10} node={o.get('node','?'):<10} {o['dur']:>7.1f}s")
    # read RTTs
    reads = [o["dur"] for o in ops if o["kind"] == "read"]
    if reads:
        print(f"\n-- read_messages RTT: n={len(reads)} max={max(reads):.1f}s "
              f"mean={sum(reads)/len(reads):.2f}s (>1s = blocking concern) --")
    for kind in ("status", "tokens"):
        ks = [o["dur"] for o in ops if o["kind"] == kind]
        if ks:
            print(f"  {kind}: n={len(ks)} max={max(ks):.2f}s mean={sum(ks)/len(ks):.3f}s")
    # total time sunk in remote ops vs idle
    sunk = sum(o["dur"] for o in ops if o["kind"] in ("send", "read", "status", "tokens"))
    print(f"\n  time sunk in remote ops: {sunk:.1f}s of {wall:.1f}s wall "
          f"({100*sunk/max(wall,1e-9):.0f}%)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--task", default="实现 add(x, y) 返回两数之和，写 add.py 与 test_add.py 并跑通 pytest")
    ap.add_argument("--timeout", type=float, default=900.0)
    ap.add_argument("--ledger", default="/tmp/opencode/e2e.ledger.jsonl")
    ap.add_argument("--base", default="http://127.0.0.1:4097")
    a = ap.parse_args()

    settings = Settings(base_url=a.base, request_timeout=a.timeout, task_control_dir=None)
    sm = load_regime()
    ledger = Ledger(a.ledger)
    client = TimingClient(a.base, settings.model, timeout=a.timeout)
    driver = StatechartDriver(settings, sm, client, ledger)

    t0 = time.monotonic()
    try:
        outcome, end, detail = driver.run(a.task, "e2e-debug", timeout_sec=a.timeout)
    finally:
        ledger.close()
    wall = time.monotonic() - t0
    summarize(client.ops, a.task, outcome, end, detail, wall)
    return 0 if outcome.value == "complete" else 1


if __name__ == "__main__":
    sys.exit(main())