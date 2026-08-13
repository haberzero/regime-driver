"""Tests for DialogControlUnit (the conversational control surface as a peer unit)."""

import time

from regime_driver.app.dialog_control import DialogControlUnit
from regime_driver.app.statechart_runtime import Runtime
from regime_driver.core.statechart import Signal, SignalKind


def _runtime(dialog):
    rt = Runtime(enforce_invariants=False)
    rt.register(dialog)
    return rt


def test_subscribes_and_renders_blackboard():
    rt = Runtime(enforce_invariants=False)
    d = DialogControlUnit(bus=rt.bus)
    rt.register(d)
    rt.start()
    # simulate a workflow writing metrics to the blackboard
    rt.blackboard.update(**{"w1.node": "design", "w1.state": "running",
                            "w1.node_count": 2, "w1.heartbeat": time.time()})
    out = d.render_monitor()
    rt.stop()
    assert "w1" in out
    assert "design" in out


def test_command_monitor_and_events():
    rt = Runtime(enforce_invariants=False)
    d = DialogControlUnit(bus=rt.bus)
    rt.register(d)
    rt.start()
    rt.blackboard.set("w1.node", "implement")
    rt.bus.publish("dialog-control", "watchdog_fire", {"kind": "stall", "session": "s1"})
    time.sleep(0.05)
    assert "implement" in d.command("status")
    assert "stall" in d.command("watch")
    rt.stop()


def test_command_start_invokes_launcher():
    called = {}
    d = DialogControlUnit(allow_write=True, launcher=lambda ctx, title, flow_sm=None: called.update(
        ctx=ctx, title=title) or {"workflow_id": "w9"})
    out = d.command("start 实现 add 函数")
    assert "w9" in out
    assert called["ctx"] == "实现 add 函数"


class _SC:
    """Stub session client (session deep-interaction + reclaim)."""

    def __init__(self):
        self.sessions = [{"id": "s1", "title": "dev"}, {"id": "s2", "title": "rev"}]
        self.aborted = []
        self.deleted = []

    def list_sessions(self):
        return list(self.sessions)

    def session_status_map(self):
        return {"s1": "busy", "s2": "idle"}

    def abort_session(self, sid):
        self.aborted.append(sid)

    def delete_session(self, sid):
        self.deleted.append(sid)


def test_command_sessions_lists_with_status():
    d = DialogControlUnit(session_client=_SC())
    out = d.command("sessions")
    assert "s1" in out and "busy" in out
    assert "s2" in out and "idle" in out


def test_command_sessions_busy_filter():
    d = DialogControlUnit(session_client=_SC())
    out = d.command("sessions busy")
    assert "s1" in out
    assert "s2" not in out


def test_command_abort_is_write_gated():
    sc = _SC()
    d = DialogControlUnit(session_client=sc, allow_write=False)
    out = d.command("abort s1")
    assert "门禁" in out
    assert sc.aborted == []


def test_command_abort_single_session():
    sc = _SC()
    d = DialogControlUnit(session_client=sc, allow_write=True)
    out = d.command("abort s1")
    assert "abort session s1" in out
    assert sc.aborted == ["s1"]


def test_command_abort_all():
    sc = _SC()
    d = DialogControlUnit(session_client=sc, allow_write=True)
    d.command("abort --all")
    assert sorted(sc.aborted) == ["s1", "s2"]


def test_command_reclaim_aborts_and_deletes():
    sc = _SC()
    d = DialogControlUnit(session_client=sc, allow_write=True)
    out = d.command("reclaim s1")
    assert "已回收 session s1" in out
    assert sc.aborted == ["s1"]
    assert sc.deleted == ["s1"]


def test_command_reclaim_all():
    sc = _SC()
    d = DialogControlUnit(session_client=sc, allow_write=True)
    d.command("reclaim --all")
    assert sorted(sc.aborted) == ["s1", "s2"]
    assert sorted(sc.deleted) == ["s1", "s2"]


def test_command_sessions_requires_client():
    d = DialogControlUnit(session_client=None)
    assert "未接入" in d.command("sessions")


class _FakePool:
    def list(self):
        from regime_driver.worker import WorkerInstance
        return [
            WorkerInstance("algo", "opencode-worker-algo", 4200,
                           "http://127.0.0.1:4200", "opencode-worker-algo",
                           "/ws/algo", True),
            WorkerInstance("infra", "opencode-worker-infra", 4201,
                           "http://127.0.0.1:4201", "opencode-worker-infra",
                           "/ws/infra", False),
        ]


def test_command_parallel_requires_pool():
    d = DialogControlUnit(worker_pool=None)
    assert "未接入" in d.command("parallel")


def test_command_parallel_lists_instances():
    d = DialogControlUnit(worker_pool=_FakePool())
    out = d.command("parallel")
    assert "algo" in out and "infra" in out
    assert "2 个实例" in out
    assert "✓" in out and "✗" in out  # healthy vs unhealthy marks


def test_command_inspect_reads_blackboard():
    rt = Runtime(enforce_invariants=False)
    d = DialogControlUnit(bus=rt.bus)
    rt.register(d)
    rt.start()
    rt.blackboard.set("w1.node", "test")
    rt.blackboard.set("w1.phase", "judge_wait")
    out = d.command("inspect w1")
    rt.stop()
    assert "node" in out
    assert "test" in out


def test_free_form_llm_async_non_blocking():
    """Free-form text goes to the LLM on a worker thread; the unit returns ack
    immediately and the reply arrives via drain_replies (never blocks)."""
    rt = Runtime(enforce_invariants=False)

    def fake_llm(text, context):
        time.sleep(0.1)
        return f"llm-echo:{text}"

    d = DialogControlUnit(bus=rt.bus, llm=fake_llm)
    rt.register(d)
    rt.start()
    t0 = time.monotonic()
    ack = d.command("帮我解释一下当前状态")
    assert time.monotonic() - t0 < 0.05  # returns immediately, not blocked
    assert "思考" in ack
    deadline = time.time() + 2
    while not d.replies and time.time() < deadline:
        time.sleep(0.02)
    rt.stop()
    echoes = [r for r in d.drain_replies() if "llm-echo" in r]
    assert len(echoes) == 1, f"LLM reply surfaced {len(echoes)}x (should be 1)"


def test_notify_signal_surfaced_to_user():
    rt = Runtime(enforce_invariants=False)
    d = DialogControlUnit(bus=rt.bus)
    rt.register(d)
    rt.start()
    d.deliver(Signal(SignalKind.NOTIFY, "watchdog", d.id,
                     {"text": "workflow 卡住"}))
    time.sleep(0.05)
    rt.stop()
    assert any("watchdog" in r and "卡住" in r for r in d.drain_replies())


def test_help_and_quit():
    d = DialogControlUnit()
    assert "start" in d.command("help")
    assert d.command("quit") == "__exit__"


def test_capabilities_maps_all_groups():
    """WORK_PLAN8 stage-3: `capabilities` surfaces the full capability map so a
    duty operator sees what regime-driver can do and how to trigger it — the
    dialog is the hub that makes every capability reachable, not a hidden
    subset."""
    d = DialogControlUnit()
    out = d.command("capabilities")
    # scenario groups present
    for kw in ("监控与态势", "设计新流程", "运行任务", "只读分析面", "一次性 / 运维"):
        assert kw in out, kw
    # representative reachable paths
    for kw in ("regime report", "regime events", "regime status --deep",
               "regime worker", "regime chaos", "design <flow名>",
               "flow list"):
        assert kw in out, kw
    # english alias also routes
    assert "能力地图" in d.command("cap")
    assert "能力地图" in d.command("能力")


def test_monitor_field_filter():
    rt = Runtime(enforce_invariants=False)
    d = DialogControlUnit(bus=rt.bus)
    rt.register(d)
    rt.start()
    rt.blackboard.set("w1.node", "implement")
    rt.blackboard.set("w1.state", "running")
    out = d.command("monitor node")
    rt.stop()
    # field filter: only the node-related line shows the field value
    assert "node=implement" in out
    assert out.count("node=") >= 1


def test_watch_topic_filter():
    rt = Runtime(enforce_invariants=False)
    d = DialogControlUnit(bus=rt.bus)
    rt.register(d)
    rt.start()
    rt.bus.publish("dialog-control", "watchdog_fire", {"kind": "stall", "session": "s1"})
    rt.blackboard.set("w1.node", "x")
    time.sleep(0.05)
    out = d.command("watch 10 watchdog")
    rt.stop()
    assert "stall" in out


def test_talk_forwards_to_session_client():
    """talk <sid> <msg> sends to a session and surfaces its reply async."""
    class FakeSessionClient:
        def __init__(self):
            self.sent = []
            self.reply = "session-reply"

        def send_message(self, sid, text, agent):
            self.sent.append((sid, text, agent))

        def read_messages(self, sid):
            return [type("M", (), {"role": "assistant", "reply": self.reply,
                                   "text": self.reply})()]

    sc = FakeSessionClient()
    d = DialogControlUnit(allow_write=True, session_client=sc)
    ack = d.command("talk ses_abc 你好")
    assert "ses_abc" in ack
    assert sc.sent[-1][0] == "ses_abc"
    deadline = time.time() + 2
    while not d.replies and time.time() < deadline:
        time.sleep(0.02)
    assert any("session-reply" in r for r in d.drain_replies())


DESIGN_SPEC = (
    '{"entry": "understand", "nodes": ['
    '{"id": "understand", "desc": "理解任务", "role": "developer", "type": "agent", "next": "design"},'
    '{"id": "design", "desc": "方案设计", "role": "reviewer", "type": "judge", "next": "implement"},'
    '{"id": "implement", "desc": "实现", "role": "developer", "type": "agent", "next": null}]}'
)


def test_design_compiles_and_registers_flow():
    d = DialogControlUnit(allow_write=True)
    out = d.command(f"design myflow {DESIGN_SPEC}")
    assert "myflow" in out
    assert "understand" in out and "implement" in out
    assert d.flow_registry.sm("myflow") is not None


def test_design_invalid_spec_reports_error():
    d = DialogControlUnit(allow_write=True)
    out = d.command('design bad {"entry": "a"}')
    assert "设计失败" in out
    assert d.flow_registry.sm("bad") is None


def test_write_gate_blocks_write_ops_by_default():
    d = DialogControlUnit()  # allow_write defaults to False (read-only)
    assert "权限门禁" in d.command("start 任务")
    assert "权限门禁" in d.command("design x {}")
    assert "权限门禁" in d.command("talk s1 hi")
    # read ops still work
    assert "实时监控" in d.command("status")


def test_start_uses_designed_flow():
    launched = {}
    d = DialogControlUnit(allow_write=True, launcher=lambda ctx, title, flow_sm=None: launched.update(
        ctx=ctx, flow=flow_sm) or {"workflow_id": "w1"})
    d.command(f"design myflow {DESIGN_SPEC}")
    d.command("start myflow 做任务")
    assert launched["ctx"].strip() == "做任务"
    assert launched["flow"] is d.flow_registry.sm("myflow")


def test_compile_flow_full_regime_dict():
    from regime_driver.app.dialog_control import compile_flow
    full = ('{"version": "t", "flows": {"f": {"nodes": {"a": {"id": "a", "desc": "d",'
            '"role": "developer", "type": "agent", "next": null}}}}, '
            '"entry": {"flow": "f", "start_node": "a"}}')
    sm = compile_flow("f", full)
    assert sm.flow_path() == ["a"]


def test_flow_list_lists_designed_and_builtin():
    d = DialogControlUnit(allow_write=True)
    d.command(f"design myflow {DESIGN_SPEC}")
    out = d.command("flow list")
    assert "myflow" in out
    assert "design" in out


def test_flow_validate_file(tmp_path):
    from regime_driver.app.dialog_control import DialogControlUnit as G
    d = G()
    p = tmp_path / "f.json"
    p.write_text(
        '{"version": "t", "flows": {"f": {"nodes": {'
        '"a": {"id": "a", "desc": "d", "role": "developer", "type": "agent", "next": null}}}}, '
        '"entry": {"flow": "f", "start_node": "a"}}', encoding="utf-8")
    out = d.command(f"flow validate {p}")
    assert "校验通过" in out
    bad = tmp_path / "bad.json"
    bad.write_text(
        '{"version": "t", "flows": {"f": {"nodes": {'
        '"a": {"id": "a", "desc": "d", "role": "ghost", "type": "agent", "next": null}}}}, '
        '"entry": {"flow": "f", "start_node": "a"}}', encoding="utf-8")
    out = d.command(f"flow validate {bad}")
    assert "校验失败" in out


def test_flow_reload_is_write_gated():
    d = DialogControlUnit()  # read-only by default
    assert "门禁" in d.command("flow reload x")


def test_doctor_self_check():
    d = DialogControlUnit()
    out = d.command("doctor")
    assert "自检" in out
    assert "离线模式" in out          # no session_client -> offline worker check
    assert "已注册 flow" in out
    assert "只读" in out               # allow_write=False default


def test_doctor_with_client_reports_health():
    class _SCHealth:
        def health(self):
            return True
    d = DialogControlUnit(session_client=_SCHealth())
    out = d.command("doctor")
    assert "✓ 健康" in out


def test_design_rejects_deep_invalid_spec():
    d = DialogControlUnit(allow_write=True)
    # unknown role passes structural compile but fails deep validation (F9)
    out = d.command('design bad {"entry": "a", "nodes": [{"id": "a", "desc": "d",'
                    '"role": "ghost", "type": "agent", "next": null}]}')
    assert "设计失败" in out
    assert "deep validation" in out
    assert d.flow_registry.sm("bad") is None