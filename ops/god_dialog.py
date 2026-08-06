"""God Dialog REPL demo — one dialog that controls & monitors workflows.

Runs a StatechartCluster (constitution + workflows) with the GodDialogUnit on
the same Runtime, so the dialog sees every workflow's metrics live and can
start / inspect / monitor them. Uses MockClient by default (offline, no LLM);
pass --live to use the real worker.

Usage:
  python ops/god_dialog.py                  # offline (MockClient, no LLM)
  python ops/god_dialog.py --live           # real worker (deepseek-api)
  python ops/god_dialog.py --help
"""
from __future__ import annotations

import argparse
import sys
import time

sys.path.insert(0, "/home/haber/oc-meta/src")
sys.path.insert(0, "/home/haber/oc-meta/workflow-regime")

from regime_driver.app.god_dialog import GodDialogUnit
from regime_driver.app.statechart_cluster import StatechartCluster
from regime_driver.infra.opencode import OpenCodeClient
from regime_driver.infra.regime_loader import load_regime
from regime_driver.infra.settings import Settings
from regime_driver.testing import MockClient

BANNER = (
    "\n=== 上帝对话框 (God Dialog) ===\n"
    "唯一对话面：用自然语言控制/监控所有 workflow。输入 help 看命令。\n"
    "提示：start <任务> 启动一个 workflow；status 看实时监控；quit 退出。\n"
)


def _make_llm(base: str, model: str, timeout: float):
    """A worker-thread LLM runner backed by the opencode client (async explain)."""
    client = OpenCodeClient(base, model=model, timeout=timeout)

    def run(text, context):
        sid = client.create_session("god-dialog-explain")
        prompt = (
            "你是制度流程机器人的上帝对话框，负责向用户解释系统状态。\n"
            f"用户问题：{text}\n\n当前系统状态快照：\n{context}\n\n"
            "请用简洁中文回答，说明要点并给出下一步建议。"
        )
        client.send_message(sid, prompt, "developer")
        dl = time.time() + timeout
        while time.time() < dl:
            msgs = client.read_messages(sid)
            for m in reversed(msgs):
                if getattr(m, "role", None) == "assistant" and (m.reply or m.text).strip():
                    return (m.reply or m.text).strip()
            time.sleep(1)
        return "(LLM 超时)"

    return run


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="use the real worker")
    ap.add_argument("--base", default="http://127.0.0.1:4097")
    ap.add_argument("--model", default="deepseek-api/deepseek-v4-flash")
    ap.add_argument("--timeout", type=float, default=240.0)
    a = ap.parse_args()

    settings = Settings(base_url=a.base, request_timeout=a.timeout)
    sm = load_regime()

    if a.live:
        client = OpenCodeClient(a.base, model=a.model, timeout=a.timeout)
        llm = _make_llm(a.base, a.model, a.timeout)
    else:
        client = MockClient(sm=sm)
        llm = None  # offline: no LLM explain

    cluster = StatechartCluster(client)
    dialog = cluster.register_unit(GodDialogUnit(
        bus=cluster.runtime.bus, llm=llm,
        settings_render=lambda: settings.model_dump().__str__()))

    def launcher(ctx, title):
        wid = f"god-{len(cluster.workflows) + 1}"
        cluster.add_workflow(wid, settings, sm)
        cluster.start()
        cluster.submit(wid, ctx, title)
        return {"workflow_id": wid}

    dialog.launcher = launcher
    cluster.start()

    print(BANNER)
    print(dialog.command("status"))
    try:
        while True:
            try:
                line = input("God> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("\n再见。")
                break
            if not line:
                continue
            out = dialog.command(line)
            if out == "__exit__":
                break
            print(out)
            # surface async replies (LLM / notify) after each command
            for r in dialog.drain_replies():
                print("[async]", r)
    finally:
        cluster.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())