"""GodDialogUnit — the God Dialog as a peer state machine unit (app layer).

The God Dialog is the single, persistent conversational control surface. It is
implemented as a `ThreadedUnit` that lives on the same Runtime/bus as the
workflows and constitution, so it:

  * subscribes to the bus (blackboard.changed / watchdog_fire / NOTIFY) and is
    *pushed* events — the live monitoring area (req: monitor / subscribe to
    other state machines' messages);
  * routes natural-language commands to concrete capabilities (status / start /
    inspect / watch / help / config);
  * runs its own "intelligence" (free-form -> LLM explain) on a worker thread so
    its signal loop NEVER blocks (the "dialog never blocks" invariant);
  * emits its replies back onto the bus so other units could consume them.

The unit is the brain; the REPL front-end is the thin I/O adapter (mouth/eyes).
See docs/DESIGN-god-dialog.md.
"""

from __future__ import annotations

import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from ..core.statechart import Signal, SignalKind
from .statechart_runtime import ThreadedUnit

# event topics this dialog observes
TOPIC_BLACKBOARD = "blackboard.changed"
TOPIC_WATCHDOG = "watchdog_fire"
TOPIC_GOD_REPLY = "god.reply"

# workflow metrics keys read from the blackboard (mirrors telemetry)
_METRICS = ("node", "phase", "node_count", "state", "heartbeat",
            "start_time", "wait_sid", "waiting_s")


def _topic_label(topic: str) -> str:
    """Short label for an event topic (e.g. 'blackboard.changed' -> 'blackboard')."""
    return topic.split(".")[-1]


class GodDialogUnit(ThreadedUnit):
    """A peer, event-driven state machine that is the one dialog surface."""

    def __init__(
        self,
        unit_id: str = "god",
        bus=None,
        llm: Callable[[str, str], str] | None = None,
        launcher: Callable[[str, str], dict] | None = None,
        session_client=None,
        settings_render: Callable[[], str] | None = None,
        max_events: int = 200,
    ) -> None:
        super().__init__(unit_id, bus, role="human")
        self.llm = llm
        self.launcher = launcher
        self.session_client = session_client
        self.settings_render = settings_render
        self.max_events = max_events
        self.events: deque = deque(maxlen=max_events)   # (topic, ts, payload)
        self.replies: deque[dict] = deque()             # user-facing async replies
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="god-llm")

        # pull the bus topics we care about
        self.on_event(TOPIC_BLACKBOARD, self._on_blackboard)
        self.on_event(TOPIC_WATCHDOG, self._on_watchdog)
        self.on_event(TOPIC_GOD_REPLY, self._on_god_reply)
        if bus is not None:
            self.subscribe(TOPIC_BLACKBOARD)
            self.subscribe(TOPIC_WATCHDOG)
            # NOTE: do NOT self-subscribe TOPIC_GOD_REPLY — the dialog already
            # puts its LLM reply into self.replies directly; self-subscribing
            # would double-surface it. The emit is for *external* observers.
        # receive messages addressed to the dialog
        self.register(SignalKind.NOTIFY, self._on_notify)

    # -- lifecycle ----------------------------------------------------------

    def stop(self, timeout: float = 2.0) -> None:
        super().stop(timeout)
        self._executor.shutdown(wait=False, cancel_futures=True)

    # -- event intake (live monitoring) -------------------------------------

    def _on_blackboard(self, payload: dict) -> None:
        self.events.append((TOPIC_BLACKBOARD, time.time(), payload))

    def _on_watchdog(self, payload: dict) -> None:
        self.events.append((TOPIC_WATCHDOG, time.time(), payload))

    def _on_god_reply(self, payload: dict) -> None:
        self.replies.append({"text": str(payload.get("text", "")),
                             "kind": "god", "ts": time.time()})

    def _on_notify(self, signal: Signal) -> None:
        # another unit addressed the dialog directly -> surface it
        text = signal.get("text") or signal.get("message") or f"信号 {signal.kind.value}"
        self.replies.append({"text": f"[来自 {signal.src}] {text}",
                             "kind": "notify", "ts": time.time()})

    # -- snapshot -----------------------------------------------------------

    def workflow_status(self) -> dict[str, dict]:
        """Read the shared blackboard and return per-workflow status."""
        bb = self.bus.blackboard if self.bus is not None else None
        if bb is None:
            return {}
        out: dict[str, dict] = {}
        for key in bb.keys():
            if "." not in key:
                continue
            wid, _, metric = key.rpartition(".")
            if metric not in _METRICS:
                continue
            out.setdefault(wid, {})[metric] = bb.get(key)
        return out

    def render_monitor(self, field: str | None = None) -> str:
        lines = ["=== 上帝对话框 · 实时监控 ==="]
        status = self.workflow_status()
        if not status:
            lines.append("  (尚无 workflow 上报)")
        for wid in sorted(status):
            s = status[wid]
            if field and field not in s:
                continue
            hb = s.get("heartbeat") or 0
            age = f"{time.time() - float(hb):.0f}s" if hb else "n/a"
            wait = s.get("waiting_s")
            wait_s = f" wait={wait}s" if wait is not None else ""
            tail = f" {field}={s.get(field)}" if field else ""
            lines.append(
                f"  {wid}: state={s.get('state')} node={s.get('node')} "
                f"phase={s.get('phase')} nodes={s.get('node_count')} "
                f"hb={age}{wait_s}{tail} sid={s.get('wait_sid') or ''}"
            )
        return "\n".join(lines)

    def render_events(self, limit: int = 10, topic: str | None = None) -> str:
        lines = ["=== 最近事件 ==="]
        recent = [e for e in self.events
                  if topic is None or topic in e[0] or topic in _topic_label(e[0])]
        recent = recent[-limit:]
        if not recent:
            lines.append("  (无)")
        for topic_name, ts, p in recent:
            lines.append(
                f"  {time.strftime('%H:%M:%S', time.localtime(ts))} "
                f"[{_topic_label(topic_name)}] key={p.get('key')} "
                f"{'kind=' + str(p.get('kind')) if p.get('kind') else ''}"
            )
        return "\n".join(lines)

    # -- command routing -----------------------------------------------------

    def command(self, text: str) -> str:
        """Route a natural-language command to a capability.

        Returns text to show immediately. Commands that need the LLM (free-form)
        return a short ack and deliver the real reply to `drain_replies()`.
        """
        t = text.strip()
        if not t:
            return self.render_monitor()
        low = t.lower()

        if t in ("quit", "exit", "退出"):
            return "__exit__"
        if low in ("help", "帮助", "?", "h"):
            return self._help()
        if "config" in low or "设定" in t or "配置" in t:
            return self._render_settings()
        if self._is_monitor_cmd(low, t):
            return self.render_monitor(self._field_in(t))
        if self._is_events_cmd(low, t):
            return self.render_events(self._int_in(t, default=10), self._event_topic_in(t))
        if self._is_start_cmd(low):
            return self._start(t)
        if self._is_inspect_cmd(low):
            return self._inspect(t)
        if self._is_talk_cmd(low):
            return self._talk(t)
        # free-form -> LLM explain on a worker thread (non-blocking)
        return self._explain(t)

    # -- helpers -------------------------------------------------------------

    @staticmethod
    def _is_monitor_cmd(low: str, raw: str) -> bool:
        # command-like only: bare keyword or a leading command, so a free-form
        # sentence like "帮我解释一下当前状态" falls through to the LLM.
        bare = low in ("status", "monitor", "状态", "监控", "快照")
        return bare or low.startswith(("status ", "monitor ", "监控 ", "快照 "))

    @staticmethod
    def _is_events_cmd(low: str, raw: str) -> bool:
        bare = low in ("watch", "events", "event", "事件", "watchdog")
        return bare or low.startswith(("watch ", "事件 ", "watchdog "))

    @staticmethod
    def _is_start_cmd(low: str) -> bool:
        return low.startswith(("start", "启动"))

    @staticmethod
    def _is_inspect_cmd(low: str) -> bool:
        return "inspect" in low or "查看" in low or "详情" in low

    @staticmethod
    def _is_talk_cmd(low: str) -> bool:
        return low.startswith(("talk", "对话", "message "))

    @staticmethod
    def _int_in(text: str, default: int = 10) -> int:
        for tok in text.split():
            if tok.isdigit():
                return int(tok)
        return default

    @staticmethod
    def _field_in(text: str) -> str | None:
        for name in _METRICS:
            if name in text:
                return name
        return None

    def _event_topic_in(self, text: str) -> str | None:
        low = text.lower()
        if "watchdog" in low or "卡" in text:
            return "watchdog"
        if "blackboard" in low or "黑板" in text:
            return "blackboard"
        if "notify" in low or "提示" in text:
            return "notify"
        return None

    def _start(self, text: str) -> str:
        if self.launcher is None:
            return "start 能力未接入（未提供 launcher）。"
        # extract the context after the keyword
        ctx = text
        for kw in ("start", "启动", "开始"):
            idx = text.find(kw)
            if idx >= 0:
                ctx = text[idx + len(kw):].strip()
                break
        if not ctx:
            return "用法：start <任务上下文>"
        try:
            handle = self.launcher(ctx, f"god-{int(time.time())}")
            return f"已非阻塞启动 workflow：{handle.get('workflow_id', '?')}"
        except Exception as exc:
            return f"启动失败：{exc}"

    def _inspect(self, text: str) -> str:
        bb = self.bus.blackboard if self.bus is not None else None
        if bb is None:
            return "（无黑板）"
        # find a workflow id mentioned (god-<wid> or key)
        wid = None
        for token in text.split():
            if token.startswith("god-") or token.startswith("workflow"):
                wid = token
                break
        if wid is None:
            status = self.workflow_status()
            if not status:
                return "当前无 workflow 可查看。"
            wid = sorted(status)[0]
        prefix = f"{wid}."
        keys = [k for k in bb.keys() if k.startswith(prefix)]
        if not keys:
            return f"workflow {wid} 无黑板指标。"
        lines = [f"=== inspect {wid} ==="]
        for k in sorted(keys):
            lines.append(f"  {k.split('.', 1)[1]}: {bb.get(k)}")
        return "\n".join(lines)

    def _talk(self, text: str) -> str:
        """Independent content interaction with a specific opencode session.

        `talk <session_id> <message>` forwards a message to the given opencode
        session and returns its reply. Runs on a worker thread (non-blocking);
        the reply arrives via `drain_replies()`.
        """
        if self.session_client is None:
            return "talk 能力未接入（未提供 session_client）。"
        parts = text.split(maxsplit=2)
        if len(parts) < 3:
            return "用法：talk <session_id> <message>"
        sid = parts[1]
        msg = parts[2]
        self._executor.submit(self._run_talk, sid, msg)
        return f"已向 session {sid} 发送消息，等待回复…"

    def _run_talk(self, sid: str, msg: str) -> None:
        try:
            self.session_client.send_message(sid, msg, "developer")
            deadline = time.time() + 120
            while time.time() < deadline:
                try:
                    msgs = self.session_client.read_messages(sid)
                except Exception:
                    msgs = []
                for m in reversed(msgs):
                    if getattr(m, "role", None) == "assistant" and (m.reply or m.text).strip():
                        self.replies.append({"text": f"[session {sid}] " + (m.reply or m.text).strip(),
                                             "kind": "talk", "ts": time.time()})
                        return
                time.sleep(1)
            self.replies.append({"text": f"[session {sid}] 回复超时", "kind": "talk",
                                "ts": time.time()})
        except Exception as exc:
            self.replies.append({"text": f"[session {sid}] 交互异常：{exc}", "kind": "talk",
                                 "ts": time.time()})

    def _explain(self, text: str) -> str:
        if self.llm is None:
            return ("（自由文本响应未接入 LLM；可用 help 查看命令：" +
                    "status / start / inspect / watch / config）")
        context = self.render_monitor() + "\n" + self.render_events(5)
        self._executor.submit(self._run_llm, text, context)
        return "正在思考…（结果稍后出现）"

    def _run_llm(self, text: str, context: str) -> None:
        try:
            reply = self.llm(text, context) if self.llm else ""
        except Exception as exc:
            reply = f"(LLM 异常：{exc})"
        self.replies.append({"text": reply, "kind": "llm", "ts": time.time()})
        # the dialog's own response goes back onto the bus (other units may watch)
        self.emit(TOPIC_GOD_REPLY, text=reply)

    def _render_settings(self) -> str:
        if self.settings_render is not None:
            return self.settings_render()
        return "（未提供 settings 渲染）"

    def _help(self) -> str:
        return (
            "可用命令（中英文皆可）：\n"
            "  status / monitor [字段] / 状态        —— 实时 workflow 快照（可只查 node/state/…）\n"
            "  watch [n] [watchdog|blackboard|notify]  —— 最近 n 条事件/按主题\n"
            "  start <任务上下文> / 启动 ..            —— 非阻塞启动一个 workflow\n"
            "  inspect <workflow_id> / 查看 ..         —— 查看某 workflow 黑板指标\n"
            "  talk <session_id> <内容> / 对话 ..      —— 与指定 opencode session 独立交互\n"
            "  config / 配置                           —— 当前设置\n"
            "  其它自由文本                            —— 交给 LLM 解释（worker 线程）\n"
            "  quit / exit / 退出                      —— 退出对话框"
        )

    # -- front-end API -------------------------------------------------------

    def drain_replies(self, limit: int = 20) -> list[str]:
        """Pop queued async replies (LLM results / notify) for the front-end."""
        out = []
        while self.replies and len(out) < limit:
            out.append(self.replies.popleft()["text"])
        return out