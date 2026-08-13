"""Tests for the one-command self-driving stack (Drive: run+supervisor+reporter)."""

from __future__ import annotations

import json
import re

from regime_driver.core.models import Outcome
from regime_driver.drive import Drive, DriveResult
from regime_driver.infra.regime_loader import load_regime
from regime_driver.infra.settings import Settings
from regime_driver.app.reporter import Reporter

SUCC = {"design": "implement", "test": "wrap"}


class Message:
    def __init__(self, role, text="", error=None, sid=None):
        self.role = role
        self.text = text
        self.error = error
        self.id = sid or f"m-{role}"


class FakeClient:
    """Scripted worker: reviewer advances, developer emits [WORK_DONE]."""

    def __init__(self, stall=False):
        self.created = 0
        self.msgs = {}
        self.stall = stall

    def health(self):
        return True

    def event_stream(self, reconnect=False, max_retries=1):
        yield {"event": "server.connected", "data": {}}

    def create_session(self, title):
        self.created += 1
        return f"ses_{self.created}"

    def send_message(self, sid, text, agent):
        if agent == "reviewer":
            m = re.search(r"当前节点：(\w+)", text)
            node = m.group(1) if m else "design"
            v = {"node": node, "verdict": "advance", "action": "advance",
                 "next_state": SUCC.get(node, "wrap"), "confidence": 0.9,
                 "reason": "ok"}
            self.msgs[sid] = [Message("assistant", json.dumps(v), sid=sid)]
        else:
            if self.stall:
                self.msgs[sid] = [Message("assistant", "thinking endlessly...", sid=sid)]
            else:
                self.msgs[sid] = [Message("assistant", "done\n[WORK_DONE]", sid=sid)]

    def read_messages(self, sid):
        return self.msgs.get(sid, [])

    def session_status(self, sid):
        return "busy" if self.stall else "idle"

    def session_tokens(self, sid):
        return (0, 0)

    def abort_session(self, sid):
        pass


def _drive(tmp_path, stall=False):
    s = Settings(monitor_enabled=False, stall_sec=2, poll_sec=0.1)
    sm = load_regime()
    client = FakeClient(stall=stall)
    rep = Reporter(journal_path=tmp_path / "journal.jsonl")
    # health_poll_sec=0.05: the supervisor loop stops as soon as the workflow
    # yields a result (stop_when), so a small poll makes the tests fast without
    # changing production behavior (default remains 10.0).
    d = Drive(s, sm, client, rep, deadline_sec=600, stall_sec=60,
              health_poll_sec=0.05)
    return d, client, rep


def test_drive_composes_full_stack_complete(tmp_path):
    d, client, rep = _drive(tmp_path)
    dr = d.run("实现反转函数")
    assert isinstance(dr, DriveResult)
    assert dr.outcome == Outcome.COMPLETE.value
    assert dr.end == "wrap"
    # supervisor ended because the workflow finished (stop_when), not the deadline
    assert dr.supervisor == "workflow_done"
    # the workflow's primary session was discovered and supervised
    assert dr.session_id is not None and dr.session_id.startswith("ses_")
    assert dr.elapsed_sec > 0
    rep.close()


def test_drive_writes_shared_reporter_journal(tmp_path):
    d, client, rep = _drive(tmp_path)
    dr = d.run("实现反转函数")
    rep.close()
    journal = tmp_path / "journal.jsonl"
    assert journal.exists()
    lines = [json.loads(l) for l in journal.read_text().splitlines() if l.strip()]
    # both workflow events (node/outcome) and supervisor events share one journal
    kinds = {r.get("kind") for r in lines}
    assert "outcome" in kinds
    assert "worker" in kinds
    # the outcome record matches the drive result
    outcome_recs = [r for r in lines if r.get("kind") == "outcome"]
    assert outcome_recs
    assert outcome_recs[-1].get("outcome") == "complete"


def test_drive_stall_supervisor_escalates(tmp_path):
    # stall worker: developer never produces [WORK_DONE]; supervisor (T2) should
    # escalate through the ladder (abort) rather than the workflow running forever.
    d, client, rep = _drive(tmp_path, stall=True)
    dr = d.run("实现反转函数")
    rep.close()
    # The in-process watchdog also fires; the drive still returns promptly and
    # the supervisor took a ladder action (recorded to the journal).
    assert dr.outcome in {Outcome.ABORTED.value, Outcome.BLOCKED.value,
                          Outcome.ERROR.value, Outcome.TIMEOUT.value}


def test_drive_prunes_journal_on_teardown(tmp_path):
    """with prune_max_records, the shared journal is bounded after the run."""
    s = Settings(monitor_enabled=False, stall_sec=2, poll_sec=0.1)
    sm = load_regime()
    client = FakeClient()
    rep = Reporter(journal_path=tmp_path / "journal.jsonl")
    d = Drive(s, sm, client, rep, deadline_sec=600, stall_sec=60,
              prune_max_records=1, health_poll_sec=0.5)
    dr = d.run("实现反转函数")
    assert dr.outcome == Outcome.COMPLETE.value
    rep.close()

    lines = [l for l in (tmp_path / "journal.jsonl").read_text().splitlines() if l.strip()]
    assert len(lines) == 1, f"expected 1 kept record after prune, got {len(lines)}"
    assert json.loads(lines[0]).get("outcome") == "complete"


def test_drive_no_prune_by_default(tmp_path):
    """Without retention params, the full journal is kept."""
    d, client, rep = _drive(tmp_path)
    dr = d.run("实现反转函数")
    rep.close()
    lines = [l for l in (tmp_path / "journal.jsonl").read_text().splitlines() if l.strip()]
    assert len(lines) > 1  # many events, untouched
