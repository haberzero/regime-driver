"""Tests for GodDialogUnit (the conversational control surface as a peer unit)."""

import time

from regime_driver.app.god_dialog import GodDialogUnit
from regime_driver.app.statechart_runtime import Runtime
from regime_driver.core.statechart import Signal, SignalKind


def _runtime(dialog):
    rt = Runtime(enforce_invariants=False)
    rt.register(dialog)
    return rt


def test_subscribes_and_renders_blackboard():
    rt = Runtime(enforce_invariants=False)
    d = GodDialogUnit(bus=rt.bus)
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
    d = GodDialogUnit(bus=rt.bus)
    rt.register(d)
    rt.start()
    rt.blackboard.set("w1.node", "implement")
    rt.bus.publish("god", "watchdog_fire", {"kind": "stall", "session": "s1"})
    time.sleep(0.05)
    assert "implement" in d.command("status")
    assert "stall" in d.command("watch")
    rt.stop()


def test_command_start_invokes_launcher():
    called = {}
    d = GodDialogUnit(allow_write=True, launcher=lambda ctx, title, flow_sm=None: called.update(
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
    d = GodDialogUnit(session_client=_SC())
    out = d.command("sessions")
    assert "s1" in out and "busy" in out
    assert "s2" in out and "idle" in out


def test_command_sessions_busy_filter():
    d = GodDialogUnit(session_client=_SC())
    out = d.command("sessions busy")
    assert "s1" in out
    assert "s2" not in out


def test_command_abort_is_write_gated():
    sc = _SC()
    d = GodDialogUnit(session_client=sc, allow_write=False)
    out = d.command("abort s1")
    assert "门禁" in out
    assert sc.aborted == []


def test_command_abort_single_session():
    sc = _SC()
    d = GodDialogUnit(session_client=sc, allow_write=True)
    out = d.command("abort s1")
    assert "abort session s1" in out
    assert sc.aborted == ["s1"]


def test_command_abort_all():
    sc = _SC()
    d = GodDialogUnit(session_client=sc, allow_write=True)
    d.command("abort --all")
    assert sorted(sc.aborted) == ["s1", "s2"]


def test_command_reclaim_aborts_and_deletes():
    sc = _SC()
    d = GodDialogUnit(session_client=sc, allow_write=True)
    out = d.command("reclaim s1")
    assert "已回收 session s1" in out
    assert sc.aborted == ["s1"]
    assert sc.deleted == ["s1"]


def test_command_reclaim_all():
    sc = _SC()
    d = GodDialogUnit(session_client=sc, allow_write=True)
    d.command("reclaim --all")
    assert sorted(sc.aborted) == ["s1", "s2"]
    assert sorted(sc.deleted) == ["s1", "s2"]


def test_command_sessions_requires_client():
    d = GodDialogUnit(session_client=None)
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


def test_command_fleet_requires_pool():
    d = GodDialogUnit(worker_pool=None)
    assert "未接入" in d.command("fleet")


def test_command_fleet_lists_instances():
    d = GodDialogUnit(worker_pool=_FakePool())
    out = d.command("fleet")
    assert "algo" in out and "infra" in out
    assert "2 个实例" in out
    assert "✓" in out and "✗" in out  # healthy vs unhealthy marks


def test_command_inspect_reads_blackboard():
    rt = Runtime(enforce_invariants=False)
    d = GodDialogUnit(bus=rt.bus)
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

    d = GodDialogUnit(bus=rt.bus, llm=fake_llm)
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
    d = GodDialogUnit(bus=rt.bus)
    rt.register(d)
    rt.start()
    d.deliver(Signal(SignalKind.NOTIFY, "constitution", d.id,
                     {"text": "workflow 卡住"}))
    time.sleep(0.05)
    rt.stop()
    assert any("constitution" in r and "卡住" in r for r in d.drain_replies())


def test_help_and_quit():
    d = GodDialogUnit()
    assert "start" in d.command("help")
    assert d.command("quit") == "__exit__"


def test_monitor_field_filter():
    rt = Runtime(enforce_invariants=False)
    d = GodDialogUnit(bus=rt.bus)
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
    d = GodDialogUnit(bus=rt.bus)
    rt.register(d)
    rt.start()
    rt.bus.publish("god", "watchdog_fire", {"kind": "stall", "session": "s1"})
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
    d = GodDialogUnit(allow_write=True, session_client=sc)
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
    d = GodDialogUnit(allow_write=True)
    out = d.command(f"design myflow {DESIGN_SPEC}")
    assert "myflow" in out
    assert "understand" in out and "implement" in out
    assert "myflow" in d.flows


def test_design_invalid_spec_reports_error():
    d = GodDialogUnit(allow_write=True)
    out = d.command('design bad {"entry": "a"}')
    assert "设计失败" in out
    assert "bad" not in d.flows


def test_write_gate_blocks_write_ops_by_default():
    d = GodDialogUnit()  # allow_write defaults to False (read-only)
    assert "权限门禁" in d.command("start 任务")
    assert "权限门禁" in d.command("design x {}")
    assert "权限门禁" in d.command("talk s1 hi")
    # read ops still work
    assert "实时监控" in d.command("status")


def test_start_uses_designed_flow():
    launched = {}
    d = GodDialogUnit(allow_write=True, launcher=lambda ctx, title, flow_sm=None: launched.update(
        ctx=ctx, flow=flow_sm) or {"workflow_id": "w1"})
    d.command(f"design myflow {DESIGN_SPEC}")
    d.command("start myflow 做任务")
    assert launched["ctx"].strip() == "做任务"
    assert launched["flow"] is d.flows["myflow"]


def test_compile_flow_full_regime_dict():
    from regime_driver.app.god_dialog import compile_flow
    full = ('{"version": "t", "flows": {"f": {"nodes": {"a": {"id": "a", "desc": "d",'
            '"role": "developer", "type": "agent", "next": null}}}}, '
            '"entry": {"flow": "f", "start_node": "a"}}')
    sm = compile_flow("f", full)
    assert sm.flow_path() == ["a"]