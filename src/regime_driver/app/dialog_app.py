"""Dialog Control REPL application (single shared implementation).

The `regime dialog` CLI command delegates here, so the dialog wiring (cluster +
DialogControlUnit + launcher + REPL loop + LLM runner) lives in exactly one place.
"""

from __future__ import annotations

import time
from typing import Callable

from .dialog_control import DialogControlUnit
from .statechart_cluster import StatechartCluster
from ..extensions import load_user_hooks
from ..flow import FlowRegistry
from ..infra.drive_client import DriveClient
from ..infra.opencode import OpenCodeClient
from ..infra.regime_loader import load_regime
from ..infra.settings import Settings
from ..regime import RegimeRegistry, default_regime_store_dir
from ..testing import MockClient
from ..worker import WorkerPool


def make_llm_runner(client: DriveClient, timeout: float) -> Callable[[str, str], str]:
    """Worker-thread LLM runner for the dialog's free-form explain."""
    def run(text: str, context: str) -> str:
        sid = client.create_session("dialog-control-explain")
        prompt = (
            "你是制度流程机器人的控制对话框，负责向用户解释系统状态。\n"
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
    """Build the dialog cluster + DialogControlUnit and run the REPL loop.

    `allow_write` gates the DialogControlUnit's write operations (start/design/talk);
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

    # unified extension registry: the dialog owns the live registry so
    # `hook list/reload` can inspect / hot-reload the user plugin. Passed to the
    # cluster at CONSTRUCTION so the watchdog (built inside) gets the hooks too.
    hooks = load_user_hooks()
    cluster = StatechartCluster(client, hooks=hooks)

    dialog = cluster.register_unit(DialogControlUnit(
        bus=cluster.runtime.bus, llm=llm, session_client=client if live else None,
        worker_pool=WorkerPool() if live else None,
        flow_registry=FlowRegistry.from_default(),
        # same persistent named-regime store as the `regime regime` CLI: a
        # regime designed here is runnable from another process (`--regime-name`).
        regime_registry=RegimeRegistry(store_dir=default_regime_store_dir()),
        hook_registry=hooks,
        settings_render=lambda: settings.model_dump().__str__(), allow_write=allow_write,
        talk_timeout_sec=settings.dialog_talk_timeout_sec))

    def launcher(ctx, title, flow_sm=None):
        wid = f"dialog-{len(cluster.workflows) + 1}"
        cluster.add_workflow(wid, settings, flow_sm or sm)
        cluster.start()
        cluster.submit(wid, ctx, title)
        return {"workflow_id": wid}

    dialog.launcher = launcher
    cluster.start()

    print_fn("=== 控制对话框 (Dialog Control) ===")
    print_fn("唯一对话面：用自然语言控制/监控所有 workflow。输入 help 看命令。")
    try:
        while True:
            try:
                line = input("Dialog> ").strip()
            except (EOFError, KeyboardInterrupt):
                print_fn("再见。")
                break
            if not line:
                continue
            out = dialog.command(line)
            if out == "__exit__":
                break
            print_fn(out)
            for r in dialog.drain_replies():
                print_fn(f"[async] {r}")
    finally:
        cluster.stop()
    return 0