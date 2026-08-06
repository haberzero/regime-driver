"""Per-node timing breakdown probe (P1: locate E2E judge/agent stalls).

Measures the full timing composition of ONE node turn (agent or judge) exactly
as the workflow unit observes it, so we can see WHERE the E2E wall-clock goes:

  - POST wait   : how long the /message POST stays open. opencode /message is a
                  streaming request; send_message() blocks until the turn
                  completes, so this is a tight upper bound on model generation.
  - completed   : when the native `info.time.completed` marker first appears via
                  read_messages (the signal the workflow unit waits on).
  - poll gap    : the polling cadence — max + mean gap between successive
                  read_messages() polls. A large max gap means the main loop's
                  poll interval is masking a faster completion.
  - read RTT    : read_messages() round-trip time. A growing RTT (esp. toward the
                  30s client timeout) on a long history indicates the GET
                  /message endpoint blocking the mixed loop.

Usage:
  python ops/probe_node_timing.py <provider/modelid> [--judge | --agent]
    e.g. python ops/probe_node_timing.py deepseek-api/deepseek-v4-flash --judge
         python ops/probe_node_timing.py deepseek-api/deepseek-v4-flash --agent
"""
from __future__ import annotations

import argparse
import sys
import threading
import time

sys.path.insert(0, "/home/haber/oc-meta/src")
from regime_driver.infra.opencode import OpenCodeClient

BASE = "http://127.0.0.1:4097"

JUDGE_PROMPT = (
    "You are the independent reviewer (L0) in an institutional-process robot. You are "
    "read-only. Your ENTIRE reply must be EXACTLY ONE STRICT JSON OBJECT and NOTHING "
    "ELSE - no prose. Output verbatim: "
    '{"node":"<id>","verdict":"issue_resolved|issue_pending|blocked|advance|human_escalate",'
    '"action":"ask_developer|request_context|advance|abort_session|report_user",'
    '"message_to_developer":null,"next_state":"<id>|null","context_requested":null,'
    '"confidence":0.0,"reason":"1-2 sentences"}\n\n'
    "Current node: design - 设计实现方案。任务上下文：实现一个返回两数较大值的函数。"
    "开发者汇报：已完成 add 函数，含正负零用例的 pytest，全部通过，无技术债。"
    "VALID_NODES (next_state must be exactly one): implement"
)

AGENT_PROMPT = (
    "【当前节点：implement】实现任务。任务上下文：实现一个返回两数较大值的函数。"
    "请完成本节点工作。完成后直接用你的最终回复给出简短结构化汇报："
    "改动文件 / 测试命令与结果 / 技术债 / 待决点。"
)


def completed_at(message) -> str | None:
    return getattr(message, "completed", None)


def run(model: str, kind: str, poll_sec: float = 2.0, window: float = 600.0) -> None:
    c = OpenCodeClient(BASE, model=model, timeout=window)
    sid = c.create_session(f"probe-{kind}-{model.split('/')[-1]}")
    prompt = JUDGE_PROMPT if kind == "judge" else AGENT_PROMPT
    agent = "reviewer" if kind == "judge" else "developer"

    t_send = time.monotonic()
    post_end = {"t": None}

    def _send() -> None:
        c.send_message(sid, prompt, agent)
        post_end["t"] = time.monotonic()

    thread = threading.Thread(target=_send, daemon=True)
    thread.start()

    polls: list[tuple[float, float]] = []  # (wall_clock, read_rtt)
    t_completed: float | None = None
    last_done = {"t": t_send}
    deadline = t_send + window
    while True:
        t0 = time.monotonic()
        try:
            msgs = c.read_messages(sid)
        except Exception as exc:
            print(f"  read_messages error: {exc}")
            break
        rtt = time.monotonic() - t0
        polls.append((time.monotonic(), rtt))
        if t_completed is None:
            for m in msgs:
                if getattr(m, "role", None) == "assistant" and completed_at(m):
                    t_completed = time.monotonic()
                    break
        if t_completed is not None and post_end["t"] is not None:
            break
        if time.monotonic() > deadline:
            break
        time.sleep(poll_sec)

    thread.join(timeout=5.0)

    now = time.monotonic()
    post_wait = (post_end["t"] - t_send) if post_end["t"] else None
    print(f"\n== node turn ({kind}) on {model} == total wall: {now - t_send:.1f}s")
    print(f"  POST wait (send_message stream open) : "
          f"{post_wait:.1f}s" if post_wait is not None else "  POST wait : (post not returned)")
    print(f"  native time.completed first seen      : "
          f"{t_completed - t_send:.1f}s" if t_completed else "  completed : (never seen)")
    if post_wait is not None and t_completed is not None:
        print(f"  completed - POST-return delta        : {t_completed - post_end['t']:.1f}s")
    if polls:
        gaps = [polls[i][0] - polls[i - 1][0] for i in range(1, len(polls))]
        rtts = [r for _, r in polls]
        print(f"  polls                                 : {len(polls)}")
        print(f"  poll gap  max/mean                    : "
              f"{max(gaps):.1f}s / {sum(gaps) / len(gaps):.1f}s" if gaps else "  poll gap : <2")
        print(f"  read_messages RTT  max/mean          : "
              f"{max(rtts):.1f}s / {sum(rtts) / len(rtts):.1f}s")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("model")
    ap.add_argument("--kind", choices=["judge", "agent"], default="judge")
    ap.add_argument("--poll", type=float, default=2.0)
    ap.add_argument("--window", type=float, default=600.0)
    a = ap.parse_args()
    run(a.model, a.kind, a.poll, a.window)