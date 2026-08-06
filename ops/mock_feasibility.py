"""Mock-layer feasibility check (offline, no network / no LLM).

Demonstrates that the SAME WorkflowUnit / StatechartDriver code runs
deterministically with a MockClient: full-flow COMPLETE, slow-judge timing,
stall -> constitution STOP, and judge error paths.

Usage: python ops/mock_feasibility.py
"""
from __future__ import annotations

import sys
import time

sys.path.insert(0, "/home/haber/oc-meta/src")

from regime_driver.app.statechart_driver import StatechartDriver
from regime_driver.app.workflow_unit import WorkflowUnit
from regime_driver.core.models import Outcome
from regime_driver.infra.regime_loader import load_regime
from regime_driver.infra.settings import Settings
from regime_driver.testing import MockClient


def _workflow(client, **overrides):
    s = Settings(monitor_enabled=False, poll_sec=0.1, **overrides)
    sm = load_regime()
    unit = WorkflowUnit(s, sm, client, poll_sec=0.05)
    return unit


def check(label: str, outcome, expect, extra=""):
    ok = outcome == expect
    print(f"[{'OK' if ok else 'FAIL'}] {label}: got {outcome.value} (want {expect.value}) {extra}")
    return ok


def main() -> int:
    results = []

    # 1) WorkflowUnit full flow offline -> COMPLETE
    c = MockClient(sm=load_regime())
    u = _workflow(c)
    u.start(); u.submit("实现反转函数"); 
    deadline = time.time() + 5
    while u.result() is None and time.time() < deadline:
        time.sleep(0.02)
    u.stop()
    results.append(check("WorkflowUnit full flow (offline)", u.result()[0], Outcome.COMPLETE))

    # 2) StatechartDriver full flow offline -> COMPLETE
    d = StatechartDriver(Settings(monitor_enabled=False, poll_sec=0.1), load_regime(),
                         MockClient(sm=load_regime()), enforce_invariants=True)
    oc, _, _ = d.run("实现反转函数")
    results.append(check("StatechartDriver full flow (offline)", oc, Outcome.COMPLETE))

    # 3) slow judge: a rule delay should be observed in wall clock
    c = MockClient(sm=load_regime())
    c.rule("reviewer", "design", delay=0.4)
    u = _workflow(c)
    t0 = time.monotonic()
    u.start(); u.submit("task")
    deadline = time.time() + 5
    while u.result() is None and time.time() < deadline:
        time.sleep(0.02)
    u.stop()
    elapsed = time.monotonic() - t0
    results.append(check("slow judge (delay=0.4s) wall >= 0.4s", u.result()[0], Outcome.COMPLETE,
                         f"wall={elapsed:.2f}s"))

    # 4) stall: developer never completes -> constitution STOP -> BLOCKED
    c = MockClient(sm=load_regime())
    c.rule("developer", "understand", stall=True)
    d = StatechartDriver(Settings(monitor_enabled=False, poll_sec=0.1, stall_sec=1),
                         load_regime(), c, enforce_invariants=True)
    oc, _, detail = d.run("会卡住")
    results.append(check("developer stall -> constitution BLOCKED", oc, Outcome.BLOCKED,
                         f"detail={detail!r}"))

    # 5) judge returns non-JSON prose -> gate rejects -> reviewer gate exhausted
    c = MockClient(sm=load_regime())
    c.rule("reviewer", "design", builder=lambda node, text: "I think it's fine, advance please.")
    u = _workflow(c)
    u.start(); u.submit("task")
    deadline = time.time() + 5
    while u.result() is None and time.time() < deadline:
        time.sleep(0.02)
    u.stop()
    oc = u.result()[0]
    results.append(check("judge prose -> gate exhausted (ERROR)", oc,
                         Outcome.ERROR, f"detail={u.result()[2]!r}"))

    print(f"\n== feasibility: pass {sum(results)}/{len(results)} ==")
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())