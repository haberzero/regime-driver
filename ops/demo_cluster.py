#!/usr/bin/env python3
"""Demo: N concurrent workflows + live telemetry on the real opencode worker.

This exercises the statechart-network architecture end to end:
  * StatechartCluster runs several WorkflowUnits concurrently on one Runtime,
    sharing one ConstitutionUnit (watchdog) and one blackboard.
  * Each workflow is isolated on the blackboard by its own id.
  * A Telemetry unit subscribes to watchdog_fire / blackboard.changed and renders
    a live status table while the workflows run.

By default it uses a judge-free regime (a single agent node) so the demo is fast
and not gated on slow concurrent reviewer judges. Pass a real task via --task to
run the full code_workflow instead.

Usage:
  python ops/demo_cluster.py [--workers N] [--task "task context"]
"""
import argparse
import sys
import time

sys.path.insert(0, "/home/haber/oc-meta/src")

from regime_driver.app.statechart_cluster import StatechartCluster
from regime_driver.app.telemetry import Telemetry
from regime_driver.core.models import Flow, Node, NodeType, Regime, RegimeMeta, FlowEntry
from regime_driver.core.role import default_roles
from regime_driver.core.state_machine import StateMachine
from regime_driver.infra.ledger import Ledger
from regime_driver.infra.opencode import OpenCodeClient
from regime_driver.infra.regime_loader import load_regime
from regime_driver.infra.settings import Settings

BASE = "http://127.0.0.1:4097"


def _judge_free_regime():
    flow = Flow(nodes={
        "a": Node(id="a", desc="只回复一行简短汇报并以 [WORK_DONE] 结尾，不做任何文件改动",
                  role="developer", type=NodeType.AGENT, next=None),
    })
    return StateMachine(Regime(version="t", meta=RegimeMeta(), flows={"f": flow},
                               entry=FlowEntry(flow="f", start_node="a")))


def main() -> int:
    ap = argparse.ArgumentParser(description="concurrent workflows + telemetry demo")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--task", default=None, help="full-task context (runs code_workflow)")
    ap.add_argument("--timeout", type=float, default=180.0)
    args = ap.parse_args()

    client = OpenCodeClient(BASE, model="deepseek-api/deepseek-v4-flash", timeout=600.0)
    sm = load_regime() if args.task else _judge_free_regime()
    roles = default_roles()
    ledger = Ledger("/tmp/demo-cluster/ledger.jsonl")

    cluster = StatechartCluster(client, ledger, stall_sec=120)
    tel = Telemetry(bus=cluster.runtime.bus)
    cluster.runtime.bus.register(tel)
    for i in range(args.workers):
        cluster.add_workflow(f"wf-{i}", Settings(base_url=BASE, poll_sec=1.5), sm, roles)

    tasks = {}
    for i in range(args.workers):
        tasks[f"wf-{i}"] = (
            args.task if args.task else f"并发任务 {i}：只回复 [WORK_DONE] 一行。"
        )

    cluster.start()
    t0 = time.time()
    for wid, ctx in tasks.items():
        cluster.submit(wid, ctx)

    while True:
        time.sleep(2)
        print(tel.render(), "\n")
        if all(cluster.workflows[w].result() is not None for w in cluster.workflows):
            break
        if time.time() - t0 > args.timeout:
            break

    cluster.stop()
    ledger.close()
    print("=== final results ===")
    for wid, wf in cluster.workflows.items():
        print(f"{wid}: {wf.result()}")
    ok = all(wf.result() and wf.result()[0].value == "complete" for wf in cluster.workflows.values())
    print("PASS" if ok else "CHECK")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())