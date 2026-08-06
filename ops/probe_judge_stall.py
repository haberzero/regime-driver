"""Decisive E2E judge-stall probe: is the judge thinking long or truly stuck?

Sends the REAL design-judge prompt (with the design-philosophy skill) to a live
reviewer session and watches `reasoning` vs `output` token growth over time.

If `reasoning` grows while `output` stays 0 for a long stretch, the judge is
legitimately thinking long and the constitution's output-only stall detection is
a false-positive kill. If both stay flat, the judge is truly stuck.

Usage: python ops/probe_judge_stall.py [--window 300] [--poll 5]
"""
from __future__ import annotations

import argparse
import sys
import threading
import time

sys.path.insert(0, "/home/haber/oc-meta/src")
sys.path.insert(0, "/home/haber/oc-meta/workflow-regime")

from regime_driver.app.reviewer import Reviewer
from regime_driver.infra.opencode import OpenCodeClient
from regime_driver.infra.regime_loader import load_regime

BASE = "http://127.0.0.1:4097"
SKILLS = "/home/haber/oc-meta/workflow-regime/skills"

# realistic developer report for the design node (from the E2E developer output)
REPORT = (
    "已完成任务分析：任务是实现 add(x, y) 返回两数之和。计划在 add.py 定义函数，"
    "边界含负数与零，test_add.py 用 pytest 覆盖正/负/零用例。当前为方案设计阶段。"
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", type=float, default=300.0)
    ap.add_argument("--poll", type=float, default=5.0)
    ap.add_argument("--model", default="deepseek-api/deepseek-v4-flash")
    a = ap.parse_args()

    sm = load_regime()
    client = OpenCodeClient(BASE, model=a.model, timeout=a.window)
    sid = client.create_session("probe-judge-stall")
    reviewer = Reviewer(client, sid, "reviewer", sm, skills_dir=SKILLS)
    prompt = reviewer.prompt_for("design", "实现 add(x, y) 返回两数之和", REPORT)

    print(f"design judge prompt len: {len(prompt)} chars")
    t0 = time.monotonic()
    post = {"done": None}

    def _send():
        try:
            client.send_message(sid, prompt, "reviewer")
            post["done"] = "ok"
        except Exception as exc:
            post["done"] = f"err: {exc}"

    threading.Thread(target=_send, daemon=True).start()
    print("judge POST dispatched (background); polling reasoning/output ...")
    deadline = t0 + a.window
    while time.monotonic() < deadline:
        try:
            reasoning, output = client.session_tokens(sid)
            status = client.session_status(sid)
        except Exception as exc:
            print(f"  poll error: {exc}")
            break
        elapsed = time.monotonic() - t0
        txt = client.read_messages(sid)
        latest_txt = ""
        for m in reversed(txt):
            if getattr(m, "role", None) == "assistant" and (m.reply or m.text).strip():
                latest_txt = (m.reply or m.text)[:80]
                break
        completed = any(getattr(m, "completed", None) for m in txt if getattr(m, "role", None) == "assistant")
        print(f"  t={elapsed:>6.1f}s status={str(status):<5} reasoning={reasoning:>5} "
              f"output={output:>5} completed={completed} post={post['done']!r} text={latest_txt!r}")
        if completed or (post["done"] and post["done"] == "ok"):
            print(f"== judge COMPLETED at {elapsed:.1f}s (reasoning={reasoning}, output={output}) ==")
            return 0
        time.sleep(a.poll)
    print(f"== judge did NOT complete within {a.window}s ==")
    return 1


if __name__ == "__main__":
    sys.exit(main())