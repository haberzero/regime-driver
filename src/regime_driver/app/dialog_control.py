"""DialogControlUnit — the Dialog Control as a peer state machine unit (app layer).

The Dialog Control is the single, persistent conversational control surface. It is
implemented as a `ThreadedUnit` that lives on the same Runtime/bus as the
workflows and watchdog, so it:

  * subscribes to the bus (blackboard.changed / watchdog_fire / NOTIFY) and is
    *pushed* events — the live monitoring area (req: monitor / subscribe to
    other state machines' messages);
  * routes natural-language commands to concrete capabilities (status / start /
    inspect / watch / help / config);
  * runs its own "intelligence" (free-form -> LLM explain) on a worker thread so
    its signal loop NEVER blocks (the "dialog never blocks" invariant);
  * emits its replies back onto the bus so other units could consume them.

The unit is the brain; the REPL front-end is the thin I/O adapter (mouth/eyes).
See docs/subsystems/06_dialog_control.md.
"""

from __future__ import annotations

import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from ..core.statechart import Signal, SignalKind
from ..flow import FlowError, FlowRegistry, compile_spec, validate_sm
from .blackboard import WORKFLOW_METRICS, status_line, workflow_status
from .statechart_runtime import ThreadedUnit

# backward-compat alias: the unified compile entry now lives in flow.py (F1).
compile_flow = compile_spec

# event topics this dialog observes
TOPIC_BLACKBOARD = "blackboard.changed"
TOPIC_WATCHDOG = "watchdog_fire"
TOPIC_DIALOG_REPLY = "dialog.reply"


def _topic_label(topic: str) -> str:
    """Short label for an event topic (e.g. 'blackboard.changed' -> 'blackboard')."""
    return topic.split(".")[-1]


class DialogControlUnit(ThreadedUnit):
    """A peer, event-driven state machine that is the one dialog surface."""

    def __init__(
        self,
        unit_id: str = "dialog-control",
        bus=None,
        llm: Callable[[str, str], str] | None = None,
        launcher: Callable[[str, str], dict] | None = None,
        session_client=None,
        settings_render: Callable[[], str] | None = None,
        worker_pool=None,
        flow_registry: FlowRegistry | None = None,
        max_events: int = 200,
        allow_write: bool = False,
    ) -> None:
        super().__init__(unit_id, bus, role="human")
        self.llm = llm
        self.launcher = launcher
        self.session_client = session_client
        self.settings_render = settings_render
        self.worker_pool = worker_pool
        self.max_events = max_events
        # permission gate (write/permission boundary): write operations
        # (start / design / talk) are disabled unless explicitly allowed. The
        # dialog is read-only by default so a confused LLM reply can never
        # trigger a side effect; the human opts in via allow_write.
        self.allow_write = allow_write
        self.talk_agent = "developer"     # agent used for `talk <sid> <msg>`
        self.talk_timeout = 120.0         # max seconds to wait for the reply
        # the named-flow single source of truth (F4): dialog-control designed/loaded flows
        # and the builtin flow all live here. `self.flows` is a read-only view.
        self.flow_registry = flow_registry or FlowRegistry()
        self.events: deque = deque(maxlen=max_events)   # (topic, ts, payload)
        self.replies: deque[dict] = deque()             # user-facing async replies
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="dialog-llm")

        # pull the bus topics we care about
        self.on_event(TOPIC_BLACKBOARD, self._on_blackboard)
        self.on_event(TOPIC_WATCHDOG, self._on_watchdog)
        self.on_event(TOPIC_DIALOG_REPLY, self._on_dialog_reply)
        if bus is not None:
            self.subscribe(TOPIC_BLACKBOARD)
            self.subscribe(TOPIC_WATCHDOG)
            # NOTE: do NOT self-subscribe TOPIC_DIALOG_REPLY — the dialog already
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

    def _on_dialog_reply(self, payload: dict) -> None:
        self.replies.append({"text": str(payload.get("text", "")),
                             "kind": "dialog-control", "ts": time.time()})

    def _on_notify(self, signal: Signal) -> None:
        # another unit addressed the dialog directly -> surface it
        text = signal.get("text") or signal.get("message") or f"信号 {signal.kind.value}"
        self.replies.append({"text": f"[来自 {signal.src}] {text}",
                             "kind": "notify", "ts": time.time()})

    # -- snapshot -----------------------------------------------------------

    def workflow_status(self) -> dict[str, dict]:
        """Read the shared blackboard and return per-workflow status (shared helper)."""
        bb = self.bus.blackboard if self.bus is not None else None
        return workflow_status(bb)

    def render_monitor(self, field: str | None = None) -> str:
        lines = ["=== 控制对话框 · 实时监控 ==="]
        status = self.workflow_status()
        if not status:
            lines.append("  (尚无 workflow 上报)")
        for wid in sorted(status):
            s = status[wid]
            if field and field not in s:
                continue
            line = status_line(wid, s)
            if field:
                line += f"  {field}={s.get(field)}"
            lines.append("  " + line)
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
        if low in ("capabilities", "cap", "能力", "能力地图"):
            return self._capabilities()
        if "config" in low or "设定" in t or "配置" in t:
            return self._render_settings()
        if self._is_monitor_cmd(low):
            return self.render_monitor(self._field_in(t))
        if self._is_events_cmd(low):
            return self.render_events(self._int_in(t, default=10), self._event_topic_in(t))
        if self._is_start_cmd(low):
            return self._write_gate(t) or self._start(t)
        if self._is_inspect_cmd(low):
            return self._inspect(t)
        if self._is_parallel_cmd(low):
            return self._parallel(t)
        if self._is_sessions_cmd(low):
            return self._sessions(t)
        if self._is_abort_cmd(low):
            return self._write_gate(t) or self._abort(t)
        if self._is_reclaim_cmd(low):
            return self._write_gate(t) or self._reclaim(t)
        if self._is_talk_cmd(low):
            return self._write_gate(t) or self._talk(t)
        if self._is_design_cmd(low):
            return self._write_gate(t) or self._design(t)
        if self._is_flow_cmd(low):
            return self._flow(t)
        if self._is_doctor_cmd(low):
            return self._doctor()
        # free-form -> LLM explain on a worker thread (non-blocking)
        return self._explain(t)

    # -- helpers -------------------------------------------------------------

    def _write_gate(self, text: str) -> str | None:
        """Return a denial message if write permission is off, else None."""
        if self.allow_write:
            return None
        cmd = text.split()[0] if text.split() else "?"
        return (f"写操作 '{cmd}' 被权限门禁拒绝（控制对话框默认只读）。"
                "如需启用，请以 allow_write=True 构造。")

    @staticmethod
    def _is_monitor_cmd(low: str) -> bool:
        # command-like only: bare keyword or a leading command, so a free-form
        # sentence like "帮我解释一下当前状态" falls through to the LLM.
        bare = low in ("status", "monitor", "状态", "监控", "快照")
        return bare or low.startswith(("status ", "monitor ", "监控 ", "快照 "))

    @staticmethod
    def _is_events_cmd(low: str) -> bool:
        bare = low in ("watch", "events", "event", "事件", "watchdog")
        return bare or low.startswith(("watch ", "事件 ", "watchdog "))

    @staticmethod
    def _is_start_cmd(low: str) -> bool:
        return low.startswith(("start", "启动"))

    @staticmethod
    def _is_design_cmd(low: str) -> bool:
        return low.startswith(("design", "设计")) or "新建流程" in low

    @staticmethod
    def _is_flow_cmd(low: str) -> bool:
        return low.startswith("flow ") or low.startswith("流程 ")

    @staticmethod
    def _is_doctor_cmd(low: str) -> bool:
        return low in ("doctor", "自检", "体检", "检查")

    @staticmethod
    def _is_inspect_cmd(low: str) -> bool:
        return "inspect" in low or "查看" in low or "详情" in low

    @staticmethod
    def _is_talk_cmd(low: str) -> bool:
        return low.startswith(("talk", "对话", "message "))

    @staticmethod
    def _is_sessions_cmd(low: str) -> bool:
        return low in ("sessions", "会话", "列表") or low.startswith(
            ("sessions ", "会话 ", "list "))

    @staticmethod
    def _is_parallel_cmd(low: str) -> bool:
        return low in ("parallel", "并行任务") or low.startswith(("parallel ", "并行任务 "))

    @staticmethod
    def _is_abort_cmd(low: str) -> bool:
        return low.startswith(("abort", "停止", "kill "))

    @staticmethod
    def _is_reclaim_cmd(low: str) -> bool:
        return low.startswith(("reclaim", "回收", "清理 "))

    @staticmethod
    def _int_in(text: str, default: int = 10) -> int:
        for tok in text.split():
            if tok.isdigit():
                return int(tok)
        return default

    @staticmethod
    def _field_in(text: str) -> str | None:
        for name in WORKFLOW_METRICS:
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
        # extract flow name (if it matches a designed flow) and the context
        flow_sm = None
        ctx = text
        for kw in ("start", "启动", "开始"):
            idx = text.find(kw)
            if idx >= 0:
                ctx = text[idx + len(kw):].strip()
                break
        if not ctx:
            return "用法：start [flow_name] <任务上下文>"
        # a leading token matching a registered flow -> run that flow
        first = ctx.split()[0] if ctx.split() else ""
        if self.flow_registry.sm(first) is not None:
            flow_sm = self.flow_registry.sm(first)
            ctx = ctx[len(first):].strip()
        if not ctx:
            ctx = first if flow_sm is None else "（默认任务）"
        try:
            handle = self.launcher(ctx, f"dialog-{int(time.time())}", flow_sm)
            return f"已非阻塞启动 workflow：{handle.get('workflow_id', '?')}"
        except Exception as exc:
            return f"启动失败：{exc}"

    def _design(self, text: str) -> str:
        """`design <flow_name> <spec>` — spec is JSON (deterministic) or natural
        language (via LLM on a worker thread). Compiles + registers a new flow."""
        parts = text.split(maxsplit=2)
        if len(parts) < 3:
            return ("用法：design <flow_name> <JSON 或自然语言描述>。\n"
                    "JSON 形如 {\"entry\":\"a\",\"nodes\":[{\"id\":\"a\",\"desc\":\"..\","
                    "\"role\":\"developer\",\"type\":\"agent\",\"next\":\"b\"}]}")
        name, spec = parts[1], parts[2]
        if spec.strip().startswith("{") or spec.strip().startswith("["):
            try:
                sm = compile_flow(name, spec)
                entry = self.flow_registry.register(name, sm, validate=True)
            except FlowError as exc:
                return f"设计失败：{exc}"
            return (f"已设计并注册 workflow '{name}'："
                    f"路径={' → '.join(entry.sm.flow_path()) or '(空)'}")
        if self.llm is None:
            return "自然语言设计需接入 LLM；当前请提供 JSON 规格。"
        self._executor.submit(self._run_design_nl, name, spec)
        return f"正在用 LLM 设计 workflow '{name}'，稍后结果出现…"

    def _run_design_nl(self, name: str, spec: str) -> None:
        try:
            prompt = (
                "请把下面的流程描述转成一个 JSON（只输出 JSON，不要其它文字）：\n"
                "{\"entry\":\"<起始node id>\",\"nodes\":[{\"id\":\"<id>\",\"desc\":\"<中文描述>\","
                "\"role\":\"developer|reviewer\",\"type\":\"agent|judge\",\"next\":\"<下一id>\"}]}\n"
                "要求：agent=开发者干活，judge=审查者判定；最后一个节点 next 为 null；"
                f"流程必须有且仅有一个起始节点。\n流程描述：{spec}"
            )
            raw = self.llm(prompt, "")
            sm = compile_flow(name, raw)
            entry = self.flow_registry.register(name, sm, validate=True)
            self.replies.append({"text": f"已用 LLM 设计并注册 workflow '{name}'："
                                         f"路径={' → '.join(entry.sm.flow_path())}",
                                 "kind": "design", "ts": time.time()})
        except Exception as exc:
            self.replies.append({"text": f"LLM 设计 workflow '{name}' 失败：{exc}",
                                 "kind": "design", "ts": time.time()})

    def _flow(self, text: str) -> str:
        """`flow list` / `flow validate <file>` / `flow reload <name>` (F7/F8).

        list/validate are read-only; reload is a write op (re-compiles + gates
        before swap), so it honours the write gate. Operates on the shared
        FlowRegistry (single source of truth).
        """
        parts = text.split(maxsplit=2)
        sub = parts[1] if len(parts) > 1 else ""
        if sub in ("list", "ls", "列表"):
            lines = ["=== flow registry ==="]
            entries = self.flow_registry.list()
            if not entries:
                lines.append("  (无注册 flow；用 design/load 添加)")
            for e in entries:
                lines.append(f"  v{e.version} {e.name} [{e.source}] "
                             f"({len(e.sm.flow.nodes)} nodes)")
            lines.append(f"  共 {len(entries)} 个")
            return "\n".join(lines)
        if sub in ("validate", "校验"):
            if len(parts) < 3:
                return "用法：flow validate <regime.json>"
            from ..flow import load_regime as _lr
            path = parts[2]
            try:
                sm = _lr(path)
                res = validate_sm(sm)
            except Exception as exc:
                return f"校验失败：{exc}"
            if res.ok:
                return (f"✓ flow '{sm.flow_name}' 校验通过 "
                        f"({len(sm.flow.nodes)} nodes)")
            return "校验失败:\n  " + "\n  ".join(res.errors)
        if sub in ("reload", "重载"):
            if len(parts) < 3:
                return "用法：flow reload <name>"
            gate = self._write_gate("flow reload")
            if gate:
                return gate
            name = parts[2]
            try:
                entry = self.flow_registry.reload(name)
            except FlowError as exc:
                return f"重载失败：{exc}"
            return (f"✓ 已热重载 flow '{name}' → v{entry.version} "
                    f"(运行中 workflow 保持旧快照)")
        return "用法：flow list | flow validate <file> | flow reload <name>"

    def _doctor(self) -> str:
        """Self-check (non-monitoring): worker health + flow registry + LLM.

        This is a readiness/self-check, distinct from the live `status` monitor.
        Read-only, always available.
        """
        lines = ["=== 控制对话框 · 自检 (doctor) ==="]
        if self.session_client is not None:
            try:
                healthy = bool(self.session_client.health())
            except Exception:
                healthy = False
            lines.append(f"  worker health: {'✓ 健康' if healthy else '✗ 异常'}")
        else:
            lines.append("  worker health: (未接入 session_client → 离线模式)")
        lines.append(f"  已注册 flow: {len(self.flow_registry.list())} 个")
        lines.append(f"  LLM 解释: {'已接入' if self.llm is not None else '未接入'}")
        lines.append(f"  写权限门禁: {'已启用' if self.allow_write else '只读'}")
        return "\n".join(lines)

    def _inspect(self, text: str) -> str:
        bb = self.bus.blackboard if self.bus is not None else None
        if bb is None:
            return "（无黑板）"
        # find a workflow id mentioned (dialog-<wid> or key)
        wid = None
        for token in text.split():
            if token.startswith("dialog-") or token.startswith("workflow"):
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

    def _sessions(self, text: str) -> str:
        """List the worker's opencode sessions with live status (deeper control).

        `sessions` / `sessions --all` lists every session; `sessions busy` lists
        only busy ones. Requires a session_client that can list + read status.
        """
        if self.session_client is None:
            return "sessions 能力未接入（未提供 session_client）。"
        low = text.lower()
        only_busy = "busy" in low
        try:
            rows = self.session_client.list_sessions()
            status_map = self.session_client.session_status_map()
        except Exception as exc:
            return f"获取会话失败：{exc}"
        lines = ["=== sessions ==="]
        shown = 0
        for s in rows:
            sid = s.get("id")
            st = status_map.get(sid) or "idle"
            if only_busy and st != "busy":
                continue
            shown += 1
            title = str(s.get("title") or "")[:24]
            lines.append(f"  {sid} [{st}] {title}")
        if shown == 0:
            lines.append("  (无)")
        lines.append(f"  共 {shown} 个")
        return "\n".join(lines)

    def _parallel(self, text: str) -> str:
        """Parallel view: list every workspace's worker instance + health.

        Requires a worker_pool (multi-instance pool). This is the whole-batch
        control-plane view — how many isolated instances, per-workspace health.
        """
        if self.worker_pool is None:
            return "parallel 能力未接入（未提供 worker_pool）。"
        try:
            instances = self.worker_pool.list()
        except Exception as exc:
            return f"获取并行任务失败：{exc}"
        lines = ["=== parallel (每工作区一个实例) ==="]
        if not instances:
            lines.append("  (无 per-workspace 实例；用 `regime worker up <ws>` 起)")
        for i in sorted(instances, key=lambda x: x.workspace):
            mark = "✓" if i.healthy else "✗"
            lines.append(f"  {mark} {i.workspace} @ {i.base_url} "
                         f"(container={i.container})")
        lines.append(f"  共 {len(instances)} 个实例")
        return "\n".join(lines)

    def _abort(self, text: str) -> str:
        """Abort a running session (or all with `abort --all`). Write-gated."""
        if self.session_client is None:
            return "abort 能力未接入（未提供 session_client）。"
        low = text.lower()
        if "--all" in low or "全部" in text:
            try:
                sids = [s.get("id") for s in self.session_client.list_sessions()
                        if s.get("id")]
            except Exception as exc:
                return f"abort --all 失败：{exc}"
            for sid in sids:
                try:
                    self.session_client.abort_session(sid)
                except Exception as exc:
                    self.replies.append({"text": f"[abort {sid}] {exc}", "kind": "abort",
                                         "ts": time.time()})
            return f"已 abort {len(sids)} 个 session。"
        parts = text.split()
        if len(parts) < 2:
            return "用法：abort <session_id> | abort --all"
        sid = parts[1]
        try:
            self.session_client.abort_session(sid)
        except Exception as exc:
            return f"abort {sid} 失败：{exc}"
        return f"已 abort session {sid}。"

    def _reclaim(self, text: str) -> str:
        """回收（reclaim）: abort + delete a session (or all with `reclaim --all`).

        Frees the worker's brain-capacity by aborting and deleting finished or
        stuck sessions. Write-gated.
        """
        if self.session_client is None:
            return "reclaim 能力未接入（未提供 session_client）。"
        low = text.lower()
        if "--all" in low or "全部" in text:
            try:
                sids = [s.get("id") for s in self.session_client.list_sessions()
                        if s.get("id")]
            except Exception as exc:
                return f"reclaim --all 失败：{exc}"
            removed = 0
            for sid in sids:
                try:
                    self.session_client.abort_session(sid)
                    self.session_client.delete_session(sid)
                    removed += 1
                except Exception as exc:
                    self.replies.append({"text": f"[reclaim {sid}] {exc}", "kind": "reclaim",
                                         "ts": time.time()})
            return f"已回收 {removed} 个 session。"
        parts = text.split()
        if len(parts) < 2:
            return "用法：reclaim <session_id> | reclaim --all"
        sid = parts[1]
        try:
            self.session_client.abort_session(sid)
            self.session_client.delete_session(sid)
        except Exception as exc:
            return f"reclaim {sid} 失败：{exc}"
        return f"已回收 session {sid}（abort + delete）。"

    def _run_talk(self, sid: str, msg: str) -> None:
        try:
            self.session_client.send_message(sid, msg, self.talk_agent)
            deadline = time.time() + self.talk_timeout
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
        self.emit(TOPIC_DIALOG_REPLY, text=reply)

    def _render_settings(self) -> str:
        if self.settings_render is not None:
            return self.settings_render()
        return "（未提供 settings 渲染）"

    def _capabilities(self) -> str:
        """Full capability map: what regime-driver can do and how to reach it
        from the dialog (WORK_PLAN8 stage-3). Groups by usage scenario so a
        duty operator sees at a glance what is available and how to trigger it.
        """
        return (
            "能力地图（regime-driver 全部能力 → 对话框内触发路径）\n"
            "\n"
            "── 监控与态势 ────────────────────────────────\n"
            "  status / monitor [字段]   实时 workflow 快照\n"
            "  watch [n] [主题]          最近事件 / watchdog / notify\n"
            "  sessions [busy]           worker 会话及实时状态\n"
            "  parallel / 并行任务        全部工作区实例 + 健康\n"
            "  doctor / 自检              自检 worker 健康 / flow / LLM / 权限\n"
            "  inspect <wid>             某 workflow 黑板指标\n"
            "\n"
            "── 设计新流程（可自我修改闭环）─────────────────\n"
            "  design <flow名> <JSON|自然语言>   设计并注册新 workflow\n"
            "  flow list / validate / reload / 重载  热编译与热加载\n"
            "\n"
            "── 运行任务 ────────────────────────────────\n"
            "  start [flow名] <任务> / 启动 ..      非阻塞启动 workflow\n"
            "  talk <session_id> <内容>            与指定 session 独立交互\n"
            "  abort / reclaim <session_id>         中止 / 回收会话(写)\n"
            "\n"
            "── 只读分析面（对话框外的 CLI，值守时可另开终端）──\n"
            "  regime report      报告总线宏观看板 / 因果链 / 模板\n"
            "  regime events      事件账本（--follow 实时）\n"
            "  regime status --deep   一次拿全聚合态势\n"
            "  regime task/job    受监管任务 / 后台作业查询\n"
            "  regime flow inspect 查看命名 flow 定义\n"
            "\n"
            "── 一次性 / 运维（不在值守常态）────────────────\n"
            "  regime scaffold    部署官方模板到 opencode 配置\n"
            "  regime worker      多工作区实例池\n"
            "  regime chaos       故障注入 / 恢复演练\n"
            "  regime gate        手工验证 reviewer verdict JSON\n"
            "\n"
            "对话框内所有能力均经权限门禁（--perm）控制写操作。"
        )

    def _help(self) -> str:
        return (
            "可用命令（中英文皆可）：\n"
            "  capabilities / cap / 能力 / 能力地图 —— 全部能力地图(按场景分组)\n"
            "  design <flow名> <JSON|自然语言>   —— 设计并注册新 workflow\n"
            "  flow list / 流程 列表             —— 列出已注册 flow\n"
            "  flow validate <regime.json> / 校验 —— 热校验一个 flow 文件\n"
            "  flow reload <flow名> / 重载       —— 原子热重载(运行中workflow不受影响)(写)\n"
            "  doctor / 自检 / 体检               —— 自检(worker健康/flow/LLM/权限)\n"
            "  status / monitor [字段] / 状态        —— 实时 workflow 快照（可只查 node/state/…）\n"
            "  watch [n] [watchdog|blackboard|notify]  —— 最近 n 条事件/按主题\n"
            "  start [flow名] <任务上下文> / 启动 ..   —— 非阻塞启动一个 workflow\n"
            "  inspect <workflow_id> / 查看 ..         —— 查看某 workflow 黑板指标\n"
            "  parallel / 并行任务                           —— 全部工作区实例 + 健康（并行任务视图）\n"
            "  sessions / 会话 [busy]                    —— 列出 worker 会话及实时状态\n"
            "  abort <session_id> | abort --all / 停止   —— 中止运行中会话(写)\n"
            "  reclaim <session_id> | reclaim --all / 回收—— 中止并删除(回收)会话(写)\n"
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