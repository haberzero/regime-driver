"""Workflow as a peer state machine unit (app layer, full refactor).

The final architecture makes the workflow itself a *governed* statechart unit
that runs in the same Runtime as the watchdog (watchdog) unit. It drives the
regime flow node by node from a **single-threaded mixed loop**: in one thread it
(a) drains inbound signals (STOP from the watchdog, etc.), (b) polls the
session it dispatched work to, and (c) steps the node machine. Because the work
is dispatched to remote sessions (which generate asynchronously), the loop stays
free between polls to react to control signals — this is the "single-thread
mixed loop" principle from ARCHITECTURE-statechart-network §5.2.1.

The unit reports its alive session state to the watchdog via REPORT signals,
and the watchdog can interrupt it with a STOP signal (abort).
"""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from ..core.branching import ConditionError, resolve_branch
from ..core.handoff import Handoff, detect_loop
from ..core.models import DEFAULT_WORK_DONE_MARKER, NodeType, Outcome
from ..core.policy import TransitionDecision, workspace_for
from ..core.role import RoleRegistry, default_roles
from ..core.segment import SegmentParser
from ..core.statechart import Signal, SignalKind
from ..core.state_machine import StateMachine
from ..core.tools import UnknownToolError, run_tool
from ..infra.ledger import Ledger
from ..infra.drive_client import DriveClient
from ..infra.opencode import is_abort_error
from ..infra.settings import Settings
from ..infra.skill_loader import SkillNotFoundError, load_skill
from ..infra.task_control import TaskControl
from .handover_policy import (
    ContextHandoverPolicy,
    build_handover_document,
    build_handover_opening,
)
from .reviewer import Reviewer
from .session_lifecycle import SessionLifecycle, SessionRotator
from .session_manager import SessionRegistry
from .sse_activity import SseActivity
from .statechart_runtime import ThreadedUnit
from .verify import render_verify_prompt_block, run_verify

# internal states
_ST_IDLE = "idle"
_ST_RUNNING = "running"
_ST_DONE = "done"
_ST_ABORTED = "aborted"
_ST_ERROR = "error"

# phases while running a node
_PH_NONE = "none"
_PH_AGENT = "agent_wait"   # agent node dispatched, polling its session
_PH_JUDGE = "judge_wait"   # judge node dispatched, polling the reviewer session
_PH_HUMAN = "human_wait"   # phase-4: awaiting a dialog decision on an ask_human checkpoint


class _LegacyPolicy:
    """Adapter exposing the JSON-policy shape for the per-role RolePolicy path."""

    def __init__(self, role_policy) -> None:
        self._rp = role_policy

    @property
    def min_continue_nodes(self) -> int:
        return 2


class WorkflowUnit(ThreadedUnit):
    """A governed state machine that drives one regime flow on remote sessions."""

    def __init__(
        self,
        settings: Settings,
        state_machine: StateMachine,
        client: DriveClient,
        ledger: Ledger | None = None,
        reporter: "Reporter | None" = None,
        roles: RoleRegistry | None = None,
        unit_id: str = "workflow",
        run_id: str | None = None,
        bus=None,
        poll_sec: float | None = None,
        sse: SseActivity | None = None,
        context_policy: ContextHandoverPolicy | None = None,
        hooks: "HookRegistry | None" = None,
    ) -> None:
        super().__init__(unit_id, bus)
        # run_id distinguishes THIS run in the report bus from prior runs, so a
        # single `regime run` does not accumulate under a constant wf_id.
        # Defaults to the unit id (e.g. per-workflow ids in a cluster).
        self.run_id = run_id or self.id
        self.settings = settings
        self.sm = state_machine
        self.client = client
        self.ledger = ledger
        self.reporter = reporter
        self.roles = roles or default_roles()
        # 阶段 2 unified extension registry: lifecycle hooks (node_enter/done,
        # transition, judge_verdict, handover) fire through it.
        self.hooks = hooks
        self.poll_sec = poll_sec or settings.poll_sec
        self.segment_parser = SegmentParser(state_machine.regime.meta.work_done_marker)
        self.sessions = SessionRegistry(client, agent_by_role={
            rid: self.roles.get(rid).agent for rid in self.roles.ids()
        })
        self.reviewers: dict[str, Reviewer] = {}
        self.task_control = (
            TaskControl(settings.task_control_dir) if settings.task_control_dir else None
        )
        self.session_lifecycle = SessionLifecycle(settings, client, self.roles)
        self.session_rotator = SessionRotator(client, self.sessions)
        # WORK_PLAN13 context-budget handover policy (optional). When set,
        # threshold negotiation + real handover documents apply; otherwise the
        # per-role RolePolicy thresholds (legacy) drive it. A regime-declared
        # policy (injected) takes precedence over the settings JSON.
        self._context_policy: ContextHandoverPolicy | None = context_policy
        if self._context_policy is None:
            try:
                self._context_policy = ContextHandoverPolicy.from_json(
                    settings.context_handover_policy_json)
            except ValueError as exc:
                self._log("context_policy_error", err=str(exc))
        self._verify_evidence: str | None = None
        self._verify_failed: bool = False
        # WORK_PLAN11 pause-abort bookkeeping: an abort sentinel we caused
        # ourselves (pause) must not be treated as an external dead session
        # while the session is recovering (see _latest_abort / _on_pause).
        self._own_abort: bool = False
        # phase-3 (W3): last logged transient message error, for throttled audit
        self._last_transient_logged = None
        # phase-4: pending ask_human checkpoint question (None when not waiting)
        self._human_question = None
        # dispatch pool: blocking send_message (up to the client timeout) runs on
        # a worker thread so the mixed loop never blocks and stays responsive to
        # STOP even while a prompt is being generated remotely.
        self._executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="dispatch")
        self._active_dispatch = None  # future of the in-flight dispatch POST
        self._dispatch_errors: list[str] = []  # last dispatch failures (for diagnostics)
        # SSE liveness tracker (WORK_PLAN10): the ONLY reliable streaming-liveness
        # signal. opencode's session_tokens are step-granular (persisted only at
        # step-finish by an async projector) so they stay 0 during a long single
        # step; the SSE /event stream (message.part.delta ...) is immediate.
        # The watchdog's stall detection reads activity_ts from our REPORTs.
        # A shared `sse` (e.g. from Drive) is the single liveness fact source so
        # in-process and out-of-process supervision observe the same stream; the
        # workflow only owns its own instance when none is injected.
        self._sse = sse or SseActivity(client)
        self._owns_sse = sse is None

        # run state
        self._state = _ST_IDLE
        self._phase = _PH_NONE
        self._node: str | None = None
        self._wait_sid: str | None = None
        self._wait_role: str | None = None
        self._goal = ""
        self._context = ""
        self._developer_report: str | None = None
        self._extra_context: str | None = None
        self._valid_targets: set[str] = set()
        self._rounds: list[tuple[str, str]] = []
        self._judge_attempts = 0
        self._retry_feedback: str | None = None
        self._node_count = 0
        self._anchor = "developer"
        self._env: dict = {"context": "", "report": "", "ok": True, "message": ""}
        self._result: tuple[Outcome, str | None, str | None] | None = None
        self._monitor_stop: str | None = None
        self._rejudge: str | None = None   # judge node awaiting a rework re-judge
        self._dialogue_rounds = 0          # ask_developer -> rework cycles
        self._last_judged_key: tuple | None = None  # identity of the judge reply already processed
        self._start_time: float | None = None
        self._phase_started: float | None = None  # when the current wait phase began
        # WORK_PLAN11 interrupt/recover: `_paused` freezes node advancement while
        # the session is aborted-but-kept for a natural "continue" recovery.
        self._paused: bool = False
        self._pause_reason: str | None = None

        # control handlers
        self.register(SignalKind.STOP, self._on_stop)
        self.register(SignalKind.PAUSE, self._on_pause)
        self.register(SignalKind.RESUME, self._on_resume)
        self.register(SignalKind.NUDGE, self._on_nudge)
        self.register(SignalKind.ESCALATE, self._on_escalate)
        self.register(SignalKind.NOTIFY, self._on_submit)  # start a run

    # -- lifecycle (ThreadedUnit override) -----------------------------------

    def stop(self, timeout: float = 2.0) -> None:
        if self._owns_sse:
            self._sse.stop()
        super().stop(timeout)
        self._executor.shutdown(wait=False, cancel_futures=True)

    def _run(self) -> None:
        """Single-threaded mixed loop: drain signals + step the node machine."""
        last_poll = 0.0
        while not self._stop.is_set():
            self._drain_signals()
            if self._state == _ST_RUNNING and not self._paused:
                now = time.monotonic()
                if now - last_poll >= self.poll_sec:
                    last_poll = now
                    try:
                        self._step()
                    except Exception as exc:
                        self._log("workflow_step_error", node=self._node, err=str(exc))
                        self._state = _ST_ERROR
                        self._result = (Outcome.ERROR, self._node, f"workflow step error: {exc}")
                        break
            elif self._paused:
                # WORK_PLAN11: a paused workflow keeps reporting to the watchdog
                # (the loop stays alive) so the watchdog can still auto-resume or
                # escalate a stuck pause — it must NOT go silent and hang.
                self._report_to_watchdog()
            if self._state in (_ST_DONE, _ST_ABORTED, _ST_ERROR):
                if self._result is not None:
                    self._log("outcome", node=self._result[1],
                              outcome=self._result[0].value,
                              detail=self._result[2] or "")
                break
            time.sleep(min(self.poll_sec, 0.1))

    def _drain_signals(self) -> None:
        """Process inbound signals (STOP from the watchdog, etc.)."""
        while True:
            try:
                sig = self._q.get_nowait()
            except Exception:
                break
            try:
                self.on_signal(sig)
            except Exception as exc:
                # never kill the loop, but never swallow silently either: audit it
                self._log("signal_handler_error", kind=str(sig.kind), err=str(exc))

    # -- control handlers -----------------------------------------------------

    def _on_stop(self, signal: Signal) -> None:
        self._monitor_stop = signal.get("reason") or "watchdog stop"
        self._cancel_running()

    def _on_pause(self, signal: Signal) -> None:
        """WORK_PLAN11 interrupt: abort the current generation but KEEP the
        session, and freeze node advancement so a later RESUME can naturally
        continue the conversation instead of restarting from scratch.

        A paused workflow keeps reporting to the watchdog (the loop is alive)
        so it is not immediately interrupted again while waiting for RESUME.
        """
        self._pause_reason = signal.get("reason") or "watchdog interrupt"
        self._paused = True
        self._abort_waiting_session(reason=self._pause_reason)
        self._own_abort = True  # the sentinel this abort leaves is OUR pause
        self._log("workflow_paused", node=self._node, reason=self._pause_reason)

    def _on_resume(self, signal: Signal) -> None:
        """WORK_PLAN11 resume: unfreeze node advancement and resume the paused
        work within the same conversation.

        * agent phase: inject a "continue" prompt so the developer resumes its
          interrupted work.
        * judge phase: re-send the original judge prompt so the reviewer re-
          decides (a reviewer is a read-only judge; nudging it with "continue"
          would produce a non-verdict reply).
        """
        if not self._paused:
            return
        self._paused = False
        self._pause_reason = None
        # pause time must NOT count against the per-node deadline: restart the
        # node budget clock so a long pause does not instantly TIMEOUT on resume.
        self._phase_started = time.time()
        try:
            if self._phase == _PH_JUDGE:
                reviewer = self._get_reviewer(self._wait_role)
                self._send_judge_prompt(reviewer, self._node)
            elif self._wait_sid is not None:
                self._dispatch(self._wait_sid, self._resume_prompt(),
                               self.sessions.agent_for(self._wait_role or "developer"))
            self._log("workflow_resumed", node=self._node, session=self._wait_sid)
        except Exception as exc:
            self._log("workflow_resume_error", node=self._node, err=str(exc))
            self._state = _ST_ERROR
            self._result = (Outcome.ERROR, self._node, f"resume failed: {exc}")

    def _on_nudge(self, signal: Signal) -> None:
        """WORK_PLAN11 nudge: a light poke (does NOT abort). A short prompt is
        sent so the session has a fresh instruction without losing its state."""
        if self._wait_sid is None:
            return
        try:
            self._dispatch(self._wait_sid, "（监督提示：请继续完成当前节点工作，并给出结构化汇报。）",
                           self.sessions.agent_for(self._wait_role or "developer"))
            self._log("workflow_nudged", node=self._node, session=self._wait_sid)
        except Exception as exc:
            self._log("workflow_nudge_error", node=self._node, err=str(exc))

    @staticmethod
    def _resume_prompt() -> str:
        return ("（监督恢复：你之前的工作被暂时中断。请从中断处继续完成当前节点，"
                "并给出简短结构化汇报：改动文件 / 测试命令与结果 / 技术债 / 待决点。）")

    def _on_escalate(self, signal: Signal) -> None:
        """WORK_PLAN11 meta-gated action: the watchdog requests an independent
        confirmation before acting. We do NOT act directly (a meta-gated rule
        must be approved by the intelligent reviewer); we record the request so
        it is visible in the journal, and let the external supervisor's
        meta_analyze / ladder decide the final action."""
        self._log("escalate_request", node=self._node,
                  action=signal.get("kind"),
                  reason=signal.get("reason"),
                  meta_gated=bool(signal.get("meta_gated")))

    def _cancel_running(self) -> None:
        if self._state == _ST_RUNNING:
            # Abort the in-flight session so the model stops producing orphan
            # work the moment the watchdog declares a stall/loop. If we only
            # mark BLOCKED, the worker keeps generating (a STOP interrupts the
            # workflow, not the session) — writing files, burning budget, and
            # polluting artifact collection with post-mortem writes.
            self._abort_waiting_session(reason=self._monitor_stop)
            self._state = _ST_ABORTED
            self._result = (Outcome.BLOCKED, self._node, f"monitor: {self._monitor_stop}")

    def _abort_waiting_session(self, reason: str | None = None) -> None:
        """Abort whatever session the workflow is currently waiting on (best-effort)."""
        if self._wait_sid is None:
            return
        try:
            self.client.abort_session(self._wait_sid)
            self._log("monitor_abort", session=self._wait_sid,
                      reason=reason or self._monitor_stop or "abort")
        except Exception as exc:
            self._log("monitor_abort_error", session=self._wait_sid, err=str(exc))

    # -- public start ---------------------------------------------------------

    def submit(self, context: str, title: str = "regime-workflow") -> None:
        """Request the flow to run on the workflow's own thread (non-blocking).

        Enqueues a start signal so the initial dispatch happens on the workflow
        thread, not the caller's (avoids blocking the caller on a long send).
        """
        self.deliver(Signal(SignalKind.NOTIFY, "user", self.id,
                            {"context": context, "title": title}))

    def _on_submit(self, signal: Signal) -> None:
        self._begin(signal.get("context", ""), signal.get("title", "regime-workflow"))

    def _begin(self, context: str, title: str) -> None:
        self._goal = context
        self._context = context
        self._env = {"context": context, "report": "", "ok": True, "message": ""}
        self._anchor = self._anchor_role()
        self.sessions.ensure(self._anchor, title)
        self._node = self.sm.flow_path()[0]
        self._state = _ST_RUNNING
        self._node_count = 0
        self._start_time = time.time()
        self._write_metrics()
        self._enter_node(self._node)

    def result(self) -> tuple[Outcome, str | None, str | None] | None:
        return self._result

    # -- stepping -------------------------------------------------------------

    def _dispatch(self, sid: str, text: str, agent: str, retries: int = 3) -> None:
        """Dispatch a prompt/send to the pool; never blocks the mixed loop.

        The remote session generates asynchronously; this unit observes progress
        by polling the session. A send failure is retried with backoff so a slow
        judge/agent is not dropped; the watchdog's heartbeat/stall detection
        is the final backstop.

        Crucial: the streaming POST /message only returns once the turn finishes,
        which is LATER than the `message.completed` / `[WORK_DONE]` marker the
        workflow uses to advance. If we dispatched the next node without waiting
        for that POST to return, the previous node's POST would still be holding a
        worker thread, and with a small pool the next dispatch would queue forever
        (the session looks "busy, no output" -> false stall kill). So we await the
        prior POST future first, waiting for true turn completion before freeing a
        pool slot for the next node. The wait stays STOP-responsive (drains signals
        and aborts early on a control state).
        """
        self._await_prior_dispatch()

        def _send() -> None:
            for attempt in range(retries + 1):
                try:
                    self.client.send_message(sid, text, agent)
                    return
                except Exception as exc:
                    self._log("dispatch_error", session=sid, attempt=attempt, err=str(exc))
                    if attempt == 0:
                        self._dispatch_errors.append(f"{agent}: {exc}")
                    if attempt < retries:
                        time.sleep(2.0 * (attempt + 1))  # backoff before retry

        self._active_dispatch = self._executor.submit(_send)

    def _await_prior_dispatch(self) -> None:
        """Wait for the previous node's POST future, staying STOP-responsive."""
        fut = self._active_dispatch
        if fut is None:
            return
        while not fut.done():
            self._drain_signals()
            if self._state in (_ST_ABORTED, _ST_ERROR, _ST_DONE):
                return  # a control signal interrupted the wait
            time.sleep(0.05)
        # consume a possible exception so it doesn't surface as an unhandled warning
        try:
            fut.result()
        except Exception:
            pass

    def _step(self) -> None:
        self._touch_heartbeat()
        if self._phase == _PH_HUMAN:
            # phase-4 ask_human checkpoint: awaits the dialog's decision with its
            # OWN timeout (`human_confirm_timeout_sec`), not the per-node deadline
            self._step_human()
            return
        if self._phase != _PH_NONE:
            # per-node wait timeout: never hang forever on a stuck idle session
            if (self._phase_started
                    and time.time() - self._phase_started > self.settings.default_deadline_sec):
                self._abort_waiting_session(
                    reason=f"node timeout after {self.settings.default_deadline_sec}s")
                self._state = _ST_ERROR
                self._result = (Outcome.TIMEOUT, self._node,
                                self._with_dispatch_diag(
                                    f"node '{self._node}' exceeded default_deadline_sec "
                                    f"({self.settings.default_deadline_sec}s)"))
                return
        if self._phase == _PH_AGENT:
            self._step_agent()
        elif self._phase == _PH_JUDGE:
            self._step_judge()

    def _touch_heartbeat(self) -> None:
        """Update the liveness heartbeat + diagnostics each step (per-workflow key)."""
        bb = self.bus.blackboard if self.bus is not None else None
        if bb is not None:
            p = f"{self.id}."
            bb.update(**{
                f"{p}heartbeat": time.time(),
                f"{p}wait_sid": self._wait_sid,
                f"{p}waiting_s": round(time.time() - self._phase_started, 1)
                if self._phase_started else 0,
            })

    def _begin_wait(self, phase: str) -> None:
        self._phase = phase
        self._phase_started = time.time()

    def _enter_node(self, node_id: str) -> None:
        node = self.sm.node(node_id)
        self._log("node_enter", node=node_id, type=node.type.value, role=node.role)
        self._fire_hooks("node_enter", node=node_id, role=node.role,
                         type=node.type.value)
        self._node = node_id
        self._node_count += 1
        self._write_metrics()
        # fresh node: reset per-node interrogation state (re-judge does not call this)
        self._dialogue_rounds = 0
        self._rounds = []
        self._extra_context = None
        if self._node_count > self.settings.max_total_nodes:
            self._state = _ST_ABORTED
            self._result = (Outcome.BLOCKED, node_id,
                            f"exceeded max_total_nodes ({self.settings.max_total_nodes})")
            return
        if node.type == NodeType.AGENT:
            self._enter_agent(node_id)
        elif node.type == NodeType.JUDGE:
            self._enter_judge(node_id)
        else:  # tool / route / gate: deterministic, transfer immediately
            self._enter_deterministic(node)

    def _enter_agent(self, node_id: str) -> None:
        role = self.sm.node(node_id).role
        sid = self.sessions.ensure(role).session_id
        try:
            instruction = self._build_instruction(node_id, self._context, role)
            self._dispatch(sid, instruction, self.sessions.agent_for(role))
        except Exception as exc:
            self._state = _ST_ERROR
            self._result = (Outcome.ERROR, node_id, str(exc))
            return
        self._wait_sid = sid
        self._wait_role = role
        self._begin_wait(_PH_AGENT)

    def _enter_judge(self, node_id: str) -> None:
        role = self.sm.node(node_id).role
        reviewer = self._get_reviewer(role)
        self._valid_targets = set(self.sm.successors(node_id))
        self._begin_wait(_PH_JUDGE)
        self._wait_sid = reviewer.session_id
        self._wait_role = role
        self._judge_attempts = 0
        self._retry_feedback = None
        self._last_judged_key = None
        # WORK_PLAN13 runtime verification evidence: if the judge node declares a
        # `verify` command, run it on the HOST now and feed the result to the
        # judge so its verdict rests on objective runtime state, not just static
        # reading. Skipped when verify is disabled (preflight/offline) or unset.
        # B3: a failure sets _verify_failed -> the gate deterministically blocks
        # advance (via an injected blocking issue in _step_judge).
        self._verify_evidence = None
        self._verify_failed = False
        verify_cmd = getattr(self.sm.node(node_id), "verify", None)
        if verify_cmd and self.settings.verify_enabled:
            res = run_verify(verify_cmd, container=self.settings.worker_container,
                             timeout=min(self.settings.request_timeout, 300.0))
            self._verify_failed = res.failed
            self._log("verify_result", node=node_id, rc=res.rc,
                      ok=res.ok, elapsed=round(res.elapsed, 1),
                      timed_out=res.timed_out,
                      tail=(res.stdout_tail or "")[:300])
            self._verify_evidence = render_verify_prompt_block(res, verify_cmd)
        self._send_judge_prompt(reviewer, node_id)

    def _send_judge_prompt(self, reviewer: Reviewer, node_id: str) -> None:
        extra = self._extra_context
        if self._verify_evidence:
            extra = (extra + "\n\n" if extra else "") + self._verify_evidence
        prompt = reviewer.prompt_for(
            node_id, self._context, self._developer_report,
            extra, self._retry_feedback, self._valid_targets,
        )
        try:
            self._dispatch(reviewer.session_id, prompt, reviewer.agent)
        except Exception as exc:
            self._state = _ST_ERROR
            self._result = (Outcome.ERROR, node_id, str(exc))

    def _step_agent(self) -> None:
        try:
            messages = self.client.read_messages(self._wait_sid)
        except Exception as exc:
            self._state = _ST_ERROR
            self._result = (Outcome.ERROR, self._node, str(exc))
            return
        done, report = self._latest_agent_done(messages)
        if done:
            self._own_abort = False  # session produced a real reply (resumed)
            rlen = len(report or "")
            self._log("node_done", node=self._node, outcome="complete",
                      report_len=rlen)
            self._fire_hooks("node_done", node=self._node, role=self._wait_role,
                             outcome="complete", report_len=rlen)
            if rlen > self.settings.report_len_warn:
                # an abnormally large report is a weak signal that the model
                # output outgrew control (e.g. pasted history / truncated-draft
                # loop). Audit it so it is visible in the journal, but do not
                # block: the reviewer judge still verifies the deliverable.
                self._log("report_len_warn", node=self._node,
                          report_len=rlen,
                          threshold=self.settings.report_len_warn)
            self._developer_report = report
            if report is not None:
                self._env["report"] = report
            self._record_worklog(self._node, report)
            if self._rejudge is not None:
                judge_node = self._rejudge
                self._rejudge = None
                self._enter_judge(judge_node)  # re-judge after rework
            else:
                self._advance()
        elif not self._paused and self._latest_abort(messages):
            # WORK_PLAN13-fix: the waiting session was aborted by an EXTERNAL
            # authority (e.g. the drive's process-external supervisor T2) with no
            # pause/recovery flow. Polling a dead session forever is a deadlock;
            # terminate honestly as BLOCKED instead (the in-process watchdog's
            # pause/resume path sets _paused=True first, so a recoverable pause
            # never lands here).
            self._log("session_external_abort", node=self._node,
                      session=self._wait_sid)
            self._state = _ST_ABORTED
            self._result = (Outcome.BLOCKED, self._node,
                            "agent session externally aborted (stalled); no recovery")
            return
        self._audit_transient(messages)
        self._report_to_watchdog()

    def _latest_agent_done(self, messages) -> tuple[bool, str | None]:
        """Detect whether the developer finished this node's work.

        Primary signal: opencode's native turn-finished marker
        (`info.time.completed` on the latest assistant message). This is more
        reliable than asking the model to emit a magic string. A `[WORK_DONE]`
        marker in the reply is kept as a fallback for short/scripted tasks.

        A message interrupted by a supervisor abort (carries `error`, or has a
        `completed` ts but `finish=None` — the abort sentinel observed on the
        real 1.18.11 worker) is NOT a finished node: its reply is a truncated
        draft, not a deliverable, so it must not advance. Every other finish
        ('stop', '', token-limit 'length', ...) advances; a truncated-but-
        finished report is still handed to the reviewer judge which decides.
        """
        for m in reversed(messages):
            if getattr(m, "role", None) != "assistant":
                continue
            if getattr(m, "error", None):
                # abort surfaced as a message error
                return False, None
            reply = (getattr(m, "reply", "") or "").strip() \
                or (getattr(m, "text", "") or "").strip()
            # native completion: the assistant turn finished
            if getattr(m, "completed", None):
                finish = getattr(m, "finish", "stop")
                if finish is None:
                    # real-client abort: completed ts set but no finish sentinel
                    return False, None
                if reply and self.segment_parser.has_segment_end(reply):
                    return True, self.segment_parser.extract_report(reply)
                return True, reply or None
            # fallback: explicit marker in a still-open reply (short/scripted)
            if reply and self.segment_parser.has_segment_end(reply):
                return True, self.segment_parser.extract_report(reply)
            return False, None
        return False, None

    def _latest_abort(self, messages) -> bool:
        """True if the MOST RECENT assistant message carries an abort sentinel
        (an abort-TYPE message error, or a completed turn with no finish — the
        real-worker abort shape). Used to detect an externally-aborted (dead)
        session.

        Phase-3 (W3): a TRANSIENT message error (model HTTP error / rate limit /
        network) is NOT an abort — the session may recover, so the workflow keeps
        polling (bounded by the per-node deadline) instead of blocking the run.
        Only a genuine abort (MessageAbortedError and friends) is a dead-session
        sentinel.

        An abort sentinel caused by OUR OWN pause (`_own_abort`, set in
        _on_pause) is NOT treated as dead: after RESUME the old sentinel stays
        the latest message until the session's reply materializes, and a
        genuine recovery must not be killed in that window. The flag clears
        automatically once a non-abort message appears."""
        for m in reversed(messages):
            if getattr(m, "role", None) != "assistant":
                continue
            err = getattr(m, "error", None)
            is_abort = bool(
                (err and is_abort_error(err))
                or (getattr(m, "completed", None)
                    and getattr(m, "finish", "stop") is None))
            if not is_abort:
                self._own_abort = False  # session resumed producing
            return is_abort and not self._own_abort
        return False

    def _latest_transient_error(self, messages) -> str | None:
        """The error text of the newest assistant message carrying a TRANSIENT
        (non-abort) error, else None. Used to audit recoverable failures without
        treating them as a dead session (W3)."""
        for m in reversed(messages):
            if getattr(m, "role", None) != "assistant":
                continue
            err = getattr(m, "error", None)
            return err if (err and not is_abort_error(err)) else None
        return None

    def _audit_transient(self, messages) -> None:
        """Surface a transient message error once per distinct (session, error)
        — recoverable, so the run keeps polling (bounded by the node deadline),
        but the failure is visible in the journal, never silently swallowed."""
        err = self._latest_transient_error(messages)
        if not err:
            return
        key = (self._wait_sid, err[:300])
        if key == self._last_transient_logged:
            return
        self._last_transient_logged = key
        self._log("message_transient_error", node=self._node,
                  session=self._wait_sid, err=err[:300])

    def _step_judge(self) -> None:
        try:
            messages = self.client.read_messages(self._wait_sid)
        except Exception as exc:
            self._state = _ST_ERROR
            self._result = (Outcome.ERROR, self._node, str(exc))
            return
        # external-abort deadlock guard FIRST (before dedup): a dead judge
        # session can never produce a verdict — and the guard must not be
        # short-circuited by the dedup key skipping an empty-reply sentinel.
        if not self._paused and self._latest_abort(messages):
            self._log("session_external_abort", node=self._node,
                      session=self._wait_sid, phase="judge")
            self._state = _ST_ABORTED
            self._result = (Outcome.BLOCKED, self._node,
                            "reviewer session externally aborted (stalled); no recovery")
            self._report_to_watchdog()
            return
        self._audit_transient(messages)
        latest = self._latest_assistant(messages)
        if latest is None:
            self._report_to_watchdog()
            return
        # skip a reply we have already processed: the judge session accumulates
        # messages, so _latest_text alone would re-parse the previous (failure)
        # reply on every poll while a re-prompt is still generating — spamming
        # duplicate send_message POSTs and starving the dispatch pool. Only act
        # once per distinct reply. Prefer the stable message id (real client);
        # fall back to the reply text for clients without an id (test doubles).
        mid = getattr(latest, "id", None)
        key = ("id", mid) if mid else (
            "text", (getattr(latest, "reply", "") or "") + (getattr(latest, "text", "") or ""))
        if key == self._last_judged_key:
            self._report_to_watchdog()
            return
        self._last_judged_key = key
        text = (getattr(latest, "reply", "") or "") or (getattr(latest, "text", "") or "")
        reviewer = self._get_reviewer(self._wait_role)
        # B3: a failed runtime verify is OBJECTIVE evidence — inject a blocking
        # issue programmatically so the gate deterministically refuses advance
        # (the reviewer may still route via ask_developer/request_context/report).
        extra_issues = None
        if self._verify_failed:
            extra_issues = [{
                "severity": "blocking",
                "summary": "运行时验证未通过（宿主 verify 命令 rc!=0/失败），未解决不得 advance",
            }]
        result = reviewer.parse_reply(text, self._node, self._valid_targets,
                                      extra_issues=extra_issues)
        if result.ok:
            self._handle_verdict(result)
        else:
            self._judge_attempts += 1
            self._retry_feedback = result.error or (
                result.gate.reason if result.gate else "unknown"
            )
            if self._judge_attempts > self.settings.max_reviewer_retries:
                self._state = _ST_ERROR
                self._result = (Outcome.ERROR, self._node, "reviewer gate exhausted")
            else:
                self._send_judge_prompt(reviewer, self._node)
        self._report_to_watchdog()

    def _handle_verdict(self, result) -> None:
        verdict = result.verdict
        action = verdict.action
        self._log("reviewer_verdict", node=self._node, verdict=verdict.verdict,
                  action=action, confidence=verdict.confidence)
        self._fire_hooks("judge_verdict", node=self._node,
                         verdict=verdict.verdict, action=action,
                         confidence=verdict.confidence)
        if action == "advance":
            target = verdict.next_state
            if target is None and not self._valid_targets:
                # terminal judge: advance to end-of-flow (COMPLETE)
                self._log("advance", to="<end>")
                self._phase = _PH_NONE
                self._phase_started = None
                self._advance(None)
                return
            if target in self._valid_targets:
                self._log("advance", to=target)
                self._phase = _PH_NONE
                self._phase_started = None
                self._advance(target)
                return
            self._state = _ST_ERROR
            self._result = (Outcome.ERROR, self._node, f"bad advance target '{target}'")
            return
        if action == "ask_developer":
            self._dialogue_rounds += 1
            if self._dialogue_rounds > self.settings.max_dialogue_rounds:
                self._state = _ST_ERROR
                self._result = (Outcome.ERROR, self._node, "reviewer dialogue rounds exhausted")
                return
            inquiry = Handoff.reviewer_inquiry(
                criticisms=[verdict.reason] if verdict.reason else [],
                required_rework=verdict.message_to_developer or "",
                flow_node=self._node,
            )
            self._log("reviewer_inquiry", node=self._node, msg=inquiry.summary)
            self._rounds.append((inquiry.inquiry_text(), self._developer_report or ""))
            if detect_loop(self._rounds, self.settings.convergence_max_identical):
                self._state = _ST_ABORTED
                self._result = (Outcome.BLOCKED, self._node,
                                "reviewer/developer interrogation is looping")
                return
            work_sid = self.sessions.ensure("developer").session_id
            try:
                self._dispatch(work_sid, inquiry.inquiry_text(),
                               self.sessions.agent_for("developer"))
            except Exception as exc:
                self._state = _ST_ERROR
                self._result = (Outcome.ERROR, self._node, str(exc))
                return
            self._rejudge = self._node
            self._wait_sid = work_sid
            self._begin_wait(_PH_AGENT)
            return
        if action == "request_context":
            self._extra_context = verdict.context_requested
            self._send_judge_prompt(self._get_reviewer(self._wait_role), self._node)
            return
        if action == "abort_session":
            self.sessions.abort("developer")
            self._state = _ST_ABORTED
            self._result = (Outcome.ABORTED, self._node, verdict.reason)
            return
        if action == "report_user":
            self._state = _ST_DONE
            self._result = (Outcome.HUMAN, self._node, verdict.reason)
            return
        if action == "ask_human":
            # phase-4 human-in-the-loop checkpoint: surface the question to the
            # dialog (blackboard.human_ask) and wait for its decision
            self._begin_human_checkpoint(
                verdict.human_question or verdict.reason or "需要人工确认")
            return
        self._state = _ST_ERROR
        self._result = (Outcome.ERROR, self._node, f"unknown action '{action}'")

    def _begin_human_checkpoint(self, question: str) -> None:
        """Surface an ask_human checkpoint and freeze advancement until the
        dialog decides (`human_decision` on the blackboard)."""
        self._human_question = question
        self._log("human_ask", node=self._node, question=question[:300],
                  session=self._wait_sid)
        bb = self.bus.blackboard if self.bus is not None else None
        if bb is not None:
            bb.update(**{
                f"{self.id}.human_ask": question,
                f"{self.id}.human_waiting": True,
                f"{self.id}.human_decision": None,
            })
        self._begin_wait(_PH_HUMAN)
        self._report_to_watchdog()

    def _clear_human_checkpoint(self) -> None:
        """Consume a human checkpoint: clear ALL its blackboard keys so a decided
        checkpoint is never listed as pending again or re-answered."""
        bb = self.bus.blackboard if self.bus is not None else None
        if bb is not None:
            bb.set(f"{self.id}.human_decision", None)
            bb.set(f"{self.id}.human_waiting", None)
            bb.set(f"{self.id}.human_ask", None)

    def _step_human(self) -> None:
        """Phase-4: poll for a dialog decision on an ask_human checkpoint.

        `decide <workflow> <yes|no> [comment]` (dialog) writes
        `{wid}.human_decision`; YES -> advance, NO -> developer rework with the
        comment. On `human_confirm_timeout_sec` without a decision the configured
        timeout default applies (`block` | `advance` | `rework`).
        """
        bb = self.bus.blackboard if self.bus is not None else None
        decision = bb.get(f"{self.id}.human_decision") if bb is not None else None
        if decision is None:
            if (self._phase_started
                    and time.time() - self._phase_started
                    > self.settings.human_confirm_timeout_sec):
                self._human_timeout_default()
            self._report_to_watchdog()
            return
        if not isinstance(decision, dict):
            # a malformed write must not kill the step loop — surface and clear
            self._log("human_decision_error", node=self._node, err=str(decision)[:200])
            self._clear_human_checkpoint()
            self._phase = _PH_NONE
            self._phase_started = None
            self._report_to_watchdog()
            return
        answer = str(decision.get("answer", "")).lower()
        comment = str(decision.get("comment", ""))
        self._log("human_decision", node=self._node, answer=answer,
                  comment=comment[:200], session=self._wait_sid)
        self._clear_human_checkpoint()  # consume ALL checkpoint keys (B3)
        self._phase = _PH_NONE
        self._phase_started = None
        if answer in ("yes", "y", "是", "确认", "通过", "approve"):
            self._advance()
        else:
            self._route_human_rework(comment or f"human answered '{answer}'")

    def _human_timeout_default(self) -> None:
        mode = self.settings.human_default_on_timeout
        self._log("human_timeout", node=self._node, default=mode)
        self._clear_human_checkpoint()
        self._phase = _PH_NONE
        self._phase_started = None
        if mode == "advance":
            self._advance()
        elif mode == "rework":
            self._route_human_rework("human confirmation timed out")
        else:  # block (safest unattended default)
            self._state = _ST_ABORTED
            self._result = (Outcome.BLOCKED, self._node,
                            "awaiting human confirmation timed out (no dialog decision)")

    def _route_human_rework(self, comment: str) -> None:
        """Send the developer back for rework with the human's comment, then
        re-judge the node (mirrors the ask_developer rework path, including the
        loop-detection bookkeeping)."""
        self._dialogue_rounds += 1
        if self._dialogue_rounds > self.settings.max_dialogue_rounds:
            self._state = _ST_ERROR
            self._result = (Outcome.ERROR, self._node, "human rework rounds exhausted")
            return
        inquiry = Handoff.reviewer_inquiry(
            criticisms=[comment] if comment else [],
            required_rework=comment or "",
            flow_node=self._node,
        )
        self._log("human_rework", node=self._node, msg=inquiry.summary)
        self._rounds.append((inquiry.inquiry_text(), self._developer_report or ""))
        if detect_loop(self._rounds, self.settings.convergence_max_identical):
            self._state = _ST_ABORTED
            self._result = (Outcome.BLOCKED, self._node,
                            "human rework is looping")
            return
        work_sid = self.sessions.ensure("developer").session_id
        try:
            self._dispatch(work_sid, inquiry.inquiry_text(),
                           self.sessions.agent_for("developer"))
        except Exception as exc:
            self._state = _ST_ERROR
            self._result = (Outcome.ERROR, self._node, str(exc))
            return
        self._rejudge = self._node
        self._wait_sid = work_sid
        self._begin_wait(_PH_AGENT)

    def _advance(self, next_node: str | None = None) -> None:
        if next_node is None:
            next_node = self.sm.next(self._node)
        if next_node is None:
            self._state = _ST_DONE
            self._result = (Outcome.COMPLETE, self._node, None)
            return
        self._apply_transition(self._node, next_node)
        if self._state == _ST_ABORTED:  # transition may have been interrupted
            return
        self.sessions.advance_round(self._anchor)
        self._check_session_capacity(next_node)
        self._phase = _PH_NONE
        self._phase_started = None
        self._enter_node(next_node)

    def _enter_deterministic(self, node) -> None:
        node_id = node.id
        if node.type == NodeType.TOOL:
            try:
                tresult = run_tool(node, self._env.get("context", self._context),
                                   self._env.get("report", self._developer_report or ""))
            except UnknownToolError as exc:
                self._state = _ST_ERROR
                self._result = (Outcome.ERROR, node_id, str(exc))
                return
            self._env["ok"] = tresult.ok
            self._env["message"] = tresult.message
            self._log("tool_done", node=node_id, tool=node.tool, ok=tresult.ok)
            target = self._resolve_det(node)
        else:  # route / gate
            try:
                target = resolve_branch(node, self._env)
            except ConditionError as exc:
                self._state = _ST_ERROR
                self._result = (Outcome.ERROR, node_id, str(exc))
                return
            if target is None and node.type == NodeType.GATE:
                self._state = _ST_ABORTED
                self._result = (Outcome.BLOCKED, node_id, f"gate '{node_id}' not satisfied")
                return
            if target is None:
                target = self.sm.next(node_id)
        if target is not None and target not in self.sm.flow.nodes:
            self._state = _ST_ERROR
            self._result = (Outcome.ERROR, node_id, f"bad branch target '{target}'")
            return
        self._advance(target)

    def _resolve_det(self, node) -> str | None:
        try:
            target = resolve_branch(node, self._env)
        except ConditionError:
            return None
        if target is not None and target in self.sm.flow.nodes:
            return target
        return self.sm.next(node.id)

    # -- helpers --------------------------------------------------------------

    def _report_to_watchdog(self) -> None:
        """Feed the alive session's state to the watchdog as a REPORT.

        A REPORT must always be sent; a read failure must never silently drop it
        (that would blind the watchdog into a false stall/loop verdict). Failures
        are recorded as auditable events and surfaced in the REPORT payload.

        Liveness is the SSE-activity timestamp (WORK_PLAN10): token counts are
        step-granular in opencode and stale during long generations, so they are
        NOT used for stall detection.
        """
        if self.bus is None or self._wait_sid is None:
            return
        payload: dict = {"session_id": self._wait_sid, "status": None,
                         "activity_ts": 0.0, "latest_text": "",
                         "latest_message_ts": 0.0, "latest_message_age": 0.0,
                         "node": self._node, "phase": self._phase,
                         "paused": self._paused,
                         "report_error": None}
        try:
            if self._phase == _PH_HUMAN:
                # a human checkpoint is BY DEFINITION idle (waiting for the
                # operator, not generating) — never a busy session the watchdog
                # could stall-kill while we wait for the decision.
                payload["status"] = "idle"
            else:
                payload["status"] = self.client.session_status(self._wait_sid)
        except Exception as exc:
            payload["report_error"] = f"status: {exc}"
            self._log("report_error", session=self._wait_sid, err=str(exc))
        payload["activity_ts"] = self._sse.last_activity(self._wait_sid)
        try:
            messages = self.client.read_messages(self._wait_sid)
            payload["latest_text"] = self._latest_text(messages)
            latest_ts = self._latest_message_ts(messages)
            payload["latest_message_ts"] = latest_ts
            if latest_ts:
                payload["latest_message_age"] = max(0.0, time.time() - latest_ts)
        except Exception as exc:
            payload["report_error"] = (
                (payload["report_error"] + "; " if payload["report_error"] else "")
                + f"read: {exc}")
            self._log("report_error", session=self._wait_sid, err=str(exc))
        self.send("watchdog", SignalKind.REPORT, payload)

    def _get_reviewer(self, role_id: str) -> Reviewer:
        if role_id not in self.reviewers:
            rev = self.sessions.ensure(role_id)
            role = self.roles.get(role_id)
            self.reviewers[role_id] = Reviewer(
                client=self.client, session_id=rev.session_id, agent=role.agent,
                state_machine=self.sm,
                skills_dir=role.skills_dir or self.settings.skills_dir,
                max_retries=self.settings.max_reviewer_retries,
            )
        return self.reviewers[role_id]

    def _anchor_role(self) -> str:
        for nid in self.sm.flow_path():
            if self.sm.node(nid).type == NodeType.AGENT:
                return self.sm.node(nid).role
        return "developer"

    def _build_instruction(self, node_id, context, role_id) -> str:
        node = self.sm.node(node_id)
        ws = workspace_for(role_id or node.role)
        ws_hint = (
            f"\n工作区：你只在 {ws['work_dir']} 目录内工作变更，可读可见目录：{', '.join(ws['visible'])}，"
            f"可写目录：{', '.join(ws['writable'])}。"
        )
        parts = [
            f"【当前节点：{node_id}】{node.desc}",
            f"任务上下文：{context}",
            ws_hint,
        ]
        if node.readonly:
            # WORK_PLAN13 node capability boundary: a readonly node must not
            # mutate the workspace — planning/reading only. File changes belong
            # to the writable nodes downstream (e.g. implement). This is what
            # keeps the design gate judging an UNBUILT plan instead of reviewing
            # already-written code.
            parts.append(
                "节点能力：本节点为【只读】——禁止修改/创建/删除任何文件，禁止运行任何写操作"
                "（写盘/编辑/安装/删除）。只允许读取文件与只读探查分析。所有文件变更必须"
                "留到后续可写节点（如 implement）完成。你的本节点产出是分析与计划/方案。"
            )
        skill = getattr(node, "skill", None)
        if skill:
            # a node's declared skill is injected into the WORKER prompt (same
            # mechanism as judge nodes): it gives the executing developer the
            # methodology/self-check for THIS node (e.g. developer-quality).
            # A missing skill is a config error -> fail loudly, not silently
            # degrade the instruction.
            skill_text = load_skill(skill, self.settings.skills_dir)
            parts.append(f"应用技能（{skill}）：\n{skill_text}")
        parts.append(
            "请完成本节点工作。完成后直接用你的最终回复给出简短结构化汇报："
            "改动文件 / 测试命令与结果 / 技术债 / 待决点。"
            f"\n汇报末尾请以 {DEFAULT_WORK_DONE_MARKER} 标记本节点工作完成。"
        )
        return "\n".join(parts)

    def _latest_text(self, messages) -> str:
        text = ""
        for m in reversed(messages):
            if getattr(m, "role", None) == "assistant" and getattr(m, "text", "").strip():
                text = m.text
                break
        return text

    def _latest_message_ts(self, messages) -> float:
        """Wall-clock SECONDS of the newest assistant message (0 if none).

        opencode emits message timestamps in millis; the mock emits seconds.
        We normalize to seconds so downstream age math is consistent. Feeds the
        watchdog policy's message-age evidence (separate from SSE activity_ts).
        """
        latest = 0.0
        for m in messages:
            if getattr(m, "role", None) != "assistant":
                continue
            ts = getattr(m, "completed", None) or getattr(m, "ts", None)
            if not ts:
                continue
            try:
                f = float(ts)
            except (TypeError, ValueError):
                continue
            if f > 1e12:  # millis -> seconds
                f /= 1000.0
            latest = max(latest, f)
        return latest

    def _latest_assistant(self, messages):
        """Return the newest COMPLETED assistant message carrying a non-empty
        reply and NO error, else None.

        The judge only parses a verdict from a message whose generation has
        FINISHED (`completed` ts set) — symmetric with the agent path
        (`_latest_agent_done`). Without this, a streaming PARTIAL reply (still
        generating) is judged on truncated text: `extract_json` returns None,
        the gate reports "no JSON object", the workflow re-prompts, and each
        re-prompt is again judged on the next partial — exhausting
        `max_reviewer_retries` on a verdict that never had a chance (the
        2026-08-15 nightly: payment_ledger error@design "reviewer gate
        exhausted", where the last complete reply was parseable but never
        judged because the dedup key had already consumed the partial).

        Phase-3 (W3): an error-carrying message is never a verdict candidate,
        so a transient error is not mis-parsed as a verdict; the judge keeps
        polling (bounded by the node deadline). A completed message with
        `finish` None is an ABORT draft (truncated text, never a deliverable —
        same shape the agent path treats as not-done); it is skipped so a
        pause-abort residue is never judged. External aborts are already
        consumed by `_latest_abort` before this is called."""
        for m in reversed(messages):
            if getattr(m, "role", None) != "assistant":
                continue
            if getattr(m, "error", None):
                continue
            if not getattr(m, "completed", None):
                continue  # streaming partial: wait for the turn to finish
            if getattr(m, "finish", "stop") is None:
                continue  # abort draft (completed ts, no finish): never a verdict
            if (getattr(m, "reply", "") or getattr(m, "text", "") or "").strip():
                return m
        return None

    def _record_worklog(self, node_id, report) -> None:
        if self.task_control is None:
            return
        self.task_control.init("worklog")
        self.task_control.append("worklog", f"节点 {node_id} 完成。\n{report or ''}")

    def _apply_transition(self, prev_node, next_node) -> None:
        # the transition DECISION is a deterministic invariant: a failure here is a
        # config/policy bug and must fail the run visibly (fail-fast), not be
        # swallowed. The rotate/handover that follows is best-effort and logged.
        prev_role = self.sm.node(prev_node).role
        policy = self.roles.get(prev_role).policy
        decision = policy.on_node_transition(prev_node, next_node, self._env)
        self._log("transition", from_node=prev_node, to_node=next_node,
                  role=prev_role, decision=decision.value)
        self._fire_hooks("transition", from_node=prev_node, to_node=next_node,
                         role=prev_role, decision=decision.value)
        if decision == TransitionDecision.ROTATE:
            try:
                state = self.sessions.get(prev_role)
                _nd = next_node if next_node in self.sm.flow.nodes else prev_node
                doc, opening = self._handover_package(
                    state, node_id=_nd, usage=0.0, kind="normal", forced=False)
                self.session_rotator.rotate_with_handover(
                    prev_role, summary=opening, handoff_kind="normal")
                self.reviewers.pop(prev_role, None)  # B1: drop stale reviewer cache
            except Exception as exc:
                self._log("transition_rotate_error", from_node=prev_node,
                          to_node=next_node, err=str(exc))

    def _check_session_capacity(self, node_id) -> None:
        """WORK_PLAN13: context-budget negotiation + real handover.

        Runs at node boundaries (after a node completes, before dispatching the
        next) — the only moment token counts are fresh (opencode persists tokens
        at step-finish). Only the session that owns the NEXT node is evaluated
        (that is the session which will actually carry the next node's work;
        checking every session would hand wrong node-context to other roles).
        When `context_handover_policy_json` is configured it drives the check:

          * >= hard_fraction  -> forced handover (no ask; context too full to
                                 trust a self-assessment),
          * soft .. hard      -> ask the session (ephemeral self-assess) for its
                                 self-interrogation budget (remaining nodes) and
                                 consent to continue in the same session; continue
                                 only with a sufficient budget, else rotate.

        A rotation always carries a REAL handover document (recent messages +
        current node + task + last report) so the fresh session has factual
        continuity, and emits a `context_handover` event for audit.
        """
        if node_id is None:
            return
        node = self.sm.node(node_id)
        state = self.sessions.get(node.role)
        if state is None:
            return
        try:
            usage = self._context_fraction(state)
            policy = self._context_policy
            if policy is not None and policy.enabled:
                if usage >= policy.hard_fraction:
                    self._rotate_session(state, node_id, usage, kind="urgent",
                                         forced=True)
                elif usage >= policy.soft_fraction:
                    self._negotiate_session(state, node_id, usage, policy)
                return
            # legacy per-role thresholds (RolePolicy)
            if state.role not in self.roles.ids():
                return
            rpol = self.roles.get(state.role).policy
            if usage < rpol.context_threshold_normal:
                return
            if rpol.is_urgent(usage):
                self._rotate_session(state, node_id, usage, kind="urgent")
            else:
                self._negotiate_session(state, node_id, usage, _LegacyPolicy(rpol))
        except Exception as exc:
            self._log("session_capacity_error", node=node_id, err=str(exc))

    def _context_fraction(self, state) -> float:
        """Fraction of the context budget used by a session (0 if unknown)."""
        try:
            reasoning, output = self.client.session_tokens(state.session_id or "")
        except Exception as exc:
            # W1: never silently fail-open — the decision to NOT hand over on a
            # token-read failure is itself a decision worth auditing.
            self._log("context_token_read_error", session=state.session_id,
                      role=state.role, err=str(exc))
            return 0.0
        total = reasoning + output
        limit = self.settings.context_limit_tokens
        return total / limit if limit else 0.0

    def _negotiate_session(self, state, node_id: str, usage: float, policy) -> None:
        """Ask the session for a self-interrogation budget + same-session consent."""
        # a custom high-threshold role might reach soft_fraction before its
        # self-assessment threshold — don't ask a session that shouldn't assess yet
        rpol = self.roles.get(state.role).policy if state.role in self.roles.ids() else None
        if rpol is not None and not rpol.should_self_assess(usage):
            return
        assessment = self.session_lifecycle.assess(state, usage)
        if assessment is None:
            # unparseable/unavailable self-assessment at an elevated context ->
            # conservative default: rotate (don't gamble on degraded quality).
            self._rotate_session(state, node_id, usage, kind="normal",
                                 reason="no self-assessment")
            return
        min_nodes = getattr(policy, "min_continue_nodes", 2)
        if assessment.verdict == "CONTINUE" and assessment.remaining_rounds_estimate >= min_nodes:
            self._log("context_negotiation", node=node_id, session=state.session_id,
                      usage=round(usage, 2), action="continue",
                      budget=assessment.remaining_rounds_estimate,
                      reason=(assessment.reason or "")[:200])
            return
        self._rotate_session(state, node_id, usage, kind="normal",
                             reason=assessment.reason,
                             assessment_summary=assessment.reason)

    def _rotate_session(self, state, node_id: str, usage: float, *, kind: str,
                        forced: bool = False, reason: str = "",
                        assessment_summary: str = "") -> None:
        """Rotate a session with a REAL handover document (WORK_PLAN13)."""
        doc, opening = self._handover_package(
            state, node_id=node_id, usage=usage, kind=kind, forced=forced)
        if assessment_summary:
            doc += f"\n- 原会话自评：{assessment_summary}"
        try:
            self.session_rotator.rotate_with_handover(
                state.role, summary=opening,
                handoff_kind="urgent" if kind == "urgent" else "normal")
        except Exception as exc:
            self._log("context_handover_error", node=node_id, err=str(exc))
            return
        # B1: the cached Reviewer holds the OLD (now full) session id; drop it so
        # `_get_reviewer` rebuilds against the fresh session (the role's judge
        # session lives in the same registry entry we just rotated).
        self.reviewers.pop(state.role, None)
        self._log("context_handover", node=node_id, session=state.session_id,
                  role=state.role, usage=round(usage, 2),
                  kind="urgent" if forced else kind,
                  forced=forced, reason=(reason or "")[:200])

    def _handover_package(self, state, node_id: str, usage: float, *,
                          kind: str, forced: bool) -> tuple[str, str]:
        """Build (document, opening) for a session rotation.

        Honors, in order of precedence (阶段 2, W-硬编码):
          1. a `handover` hook override registered in the extension registry
             (returns {"document": ..., "opening": ...}),
          2. declarative custom templates on the handover policy
             (`document_template` / `opening_template`, `.format`-style),
          3. the built-in deterministic builders.
        """
        node = self.sm.node(node_id)
        try:
            messages = self.client.read_messages(state.session_id or "")
        except Exception:
            messages = []
        policy = self._context_policy
        keep = getattr(policy, "handover_keep_messages", 30) if policy else 30
        rmax = getattr(policy, "report_max_chars", 1200) if policy else 1200
        doc = build_handover_document(
            role=state.role, node_id=node_id, node_desc=node.desc,
            task_context=self._context, messages=messages,
            last_report=self._developer_report, keep=keep, report_max_chars=rmax,
            template=getattr(policy, "document_template", None) if policy else None,
        )
        opening = build_handover_opening(
            role=state.role, node_id=node_id, node_desc=node.desc,
            task_context=self._context, document=doc, usage=usage,
            template=getattr(policy, "opening_template", None) if policy else None,
        )
        for over in self._fire_hooks("handover", role=state.role, node=node_id,
                                     usage=usage, kind=kind, forced=forced):
            if isinstance(over, dict):
                if over.get("document"):
                    doc = over["document"]
                if over.get("opening"):
                    opening = over["opening"]
        return doc, opening

    def _log(self, event, **fields) -> None:
        if self.ledger is not None:
            self.ledger.append(event, **fields)
        if self.reporter is not None:
            self.reporter.ingest(
                kind=event,
                wf_id=self.run_id,
                sm_id=self.sm.flow_name,
                session_id=fields.get("session_id") or self._wait_sid,
                node=fields.get("node"),
                outcome=fields.get("outcome"),
                event_type=event,
                detail=dict(fields),
            )

    def _fire_hooks(self, point: str, **ctx) -> list:
        """Fire a lifecycle hook through the extension registry (阶段 2).

        A hook error is audited as `hook_error` and never breaks the loop — the
        same contract as a broken watchdog rule. Returns hook returns (the
        `handover` hook uses them as overrides).
        """
        if self.hooks is None:
            return []
        return self.hooks.fire(
            point, on_error=lambda p, exc: self._log(
                "hook_error", point=p, err=str(exc)),
            **{"workflow": self.run_id, **ctx})

    def record_outcome(self, outcome: str, *, node: str | None = None,
                       detail: str = "") -> None:
        """Publicly record a run outcome to ledger/reporter (D1).

        Used by the driver when the run is externally cut short (e.g. driver
        timeout) — the workflow thread never reached a terminal state, so it
        would otherwise write no outcome event and the run would vanish from
        the report bus.
        """
        self._log("outcome", node=node or self._node,
                  outcome=outcome, detail=detail)

    def _with_dispatch_diag(self, detail: str) -> str:
        """Append recent dispatch failures to a result detail for user visibility."""
        if not self._dispatch_errors:
            return detail
        return detail + " (dispatch failures: " + "; ".join(self._dispatch_errors[-5:]) + ")"

    def _write_metrics(self) -> None:
        """Publish live runtime metrics to the shared blackboard (if any)."""
        bb = self.bus.blackboard if self.bus is not None else None
        if bb is None:
            return
        now = time.time()
        p = f"{self.id}."  # per-workflow key prefix (multi-workflow isolation)
        bb.update(**{
            f"{p}node": self._node,
            f"{p}phase": self._phase,
            f"{p}node_count": self._node_count,
            f"{p}state": self._state,
            f"{p}heartbeat": now,
            f"{p}start_time": self._start_time or now,
            f"{p}wait_sid": self._wait_sid,
            f"{p}waiting_s": round(time.time() - self._phase_started, 1) if self._phase_started else 0,
        })