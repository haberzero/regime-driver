"""God Dialog REPL application (single shared implementation).

The `regime dialog` CLI command delegates here, so the dialog wiring (cluster +
GodDialogUnit + launcher + REPL loop + LLM runner) lives in exactly one place.
"""

from __future__ import annotations

import time
from typing import Callable

from .god_dialog import GodDialogUnit
from .statechart_cluster import StatechartCluster
from ..infra.opencode import OpenCodeClient
from ..infra.regime_loader import load_regime
from ..infra.settings import Settings
from ..testing import MockClient


def make_llm_runner(client: OpenCodeClient, timeout: float) -> Callable[[str, str], str]:
    """Worker-thread LLM runner for the dialog's free-form explain."""
    def run(text: str, context: str) -> str:
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


def run_dialog(
    base_url: str,
    model: str,
    live: bool = False,
    timeout: float | None = None,
    print_fn: Callable[[str], None] = print,
    allow_write: bool = False,
) -> int:
    """Build the dialog cluster + GodDialogUnit and run the REPL loop.

    `allow_write` gates the GodDialogUnit's write operations (start/design/talk);
    the CLI passes it from the operator's effective permission level (>= run), so
    write capability is never granted unconditionally. Returns 0 on clean exit.
    """
    settings = Settings(base_url=base_url, model=model,
                        request_timeout=timeout or 240.0)
    sm = load_regime()
    if live:
        client = OpenCodeClient(base_url, model=model, timeout=settings.request_timeout)
        llm = make_llm_runner(client, settings.request_timeout)
    else:
        client = MockClient(sm=sm)
        llm = None

    cluster = StatechartCluster(client)
    god = cluster.register_unit(GodDialogUnit(
        bus=cluster.runtime.bus, llm=llm, session_client=client if live else None,
        settings_render=lambda: settings.model_dump().__str__(), allow_write=allow_write))

    def launcher(ctx, title, flow_sm=None):
        wid = f"god-{len(cluster.workflows) + 1}"
        cluster.add_workflow(wid, settings, flow_sm or sm)
        cluster.start()
        cluster.submit(wid, ctx, title)
        return {"workflow_id": wid}

    god.launcher = launcher
    cluster.start()

    print_fn("=== 上帝对话框 (God Dialog) ===")
    print_fn("唯一对话面：用自然语言控制/监控所有 workflow。输入 help 看命令。")
    try:
        while True:
            try:
                line = input("God> ").strip()
            except (EOFError, KeyboardInterrupt):
                print_fn("再见。")
                break
            if not line:
                continue
            out = god.command(line)
            if out == "__exit__":
                break
            print_fn(out)
            for r in god.drain_replies():
                print_fn(f"[async] {r}")
    finally:
        cluster.stop()
    return 0