"""Measure a realistic REVIEWER JUDGE turn latency on a chosen provider.

Isolates the judge-reasoning cost (as opposed to provider base latency, which
ops/probe_latency.py measures). Prints the full judge-turn time.
Usage: python ops/probe_judge_latency.py <provider/modelid>
"""
import json, sys, time
sys.path.insert(0, "/home/haber/oc-meta/src")
from regime_driver.infra.opencode import OpenCodeClient

BASE = "http://127.0.0.1:4097"

# realistic reviewer judge prompt (from reviewer.py SYSTEM_PROMPT + a design task)
JUDGE = (
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


def main(model):
    c = OpenCodeClient(BASE, model=model, timeout=600.0)
    sid = c.create_session(f"judge-{model.split('/')[-1]}")
    t0 = time.monotonic()
    c.send_message(sid, JUDGE, "reviewer")
    dl = time.time() + 600
    while time.time() < dl:
        msgs = c.read_messages(sid)
        if any(getattr(m, "completed", None) for m in msgs if m.role == "assistant"):
            reply = next((m.reply for m in msgs if m.role == "assistant" and m.completed), "")
            print(f"JUDGE turn on {model}: {time.monotonic()-t0:.1f}s")
            print(f"reply head: {reply[:120]!r}")
            return
        time.sleep(1)
    print(f"JUDGE turn on {model}: TIMEOUT (>600s)")


if __name__ == "__main__":
    main(sys.argv[1])