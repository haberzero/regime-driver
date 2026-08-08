"""Real-worker E2E regression (T-A).

Drives the ACTUAL opencode worker container over HTTP (the same mechanism
regime-driver uses in production) and asserts a full flow COMPLETES. This is the
"execution" verification — it proves the worker can carry a real task through
understand→…→wrap. It is gated behind REGIME_E2E=1 and a healthy worker so the
normal unit suite stays fast and offline; run explicitly for real verification:

    REGIME_E2E=1 conda run -n regime-driver python -m pytest tests/test_e2e_worker.py -q
"""

from __future__ import annotations

import json
import os
import time

import pytest

from regime_driver.app.statechart_driver import StatechartDriver
from regime_driver.core.models import Outcome
from regime_driver.infra.opencode import OpenCodeClient
from regime_driver.infra.regime_loader import load_regime
from regime_driver.infra.settings import Settings

BASE = os.environ.get("REGIME_E2E_BASE", "http://127.0.0.1:4097")


def _worker_available() -> bool:
    try:
        return OpenCodeClient(BASE, timeout=5).health()
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    os.environ.get("REGIME_E2E") != "1" or not _worker_available(),
    reason="real worker E2E: set REGIME_E2E=1 with a healthy worker at " + BASE,
)


def test_real_worker_full_flow_completes():
    settings = Settings(base_url=BASE, monitor_enabled=False, poll_sec=2.0,
                        stall_sec=180, request_timeout=240)
    sm = load_regime()
    client = OpenCodeClient(BASE, model=settings.model, timeout=settings.request_timeout)
    driver = StatechartDriver(settings, sm, client)
    outcome, end, _ = driver.run(
        "写一个Python函数 f(x)=x*2 保存到 e2e_double.py 并运行确认", timeout_sec=300)
    assert outcome == Outcome.COMPLETE, f"E2E outcome={outcome.value} end={end}"
    assert end == "wrap"


def test_real_worker_reporter_journal(tmp_path):
    """The real run should write normalized report records to a journal."""
    from regime_driver.app.reporter import Reporter

    journal = tmp_path / "e2e-report.jsonl"
    settings = Settings(base_url=BASE, monitor_enabled=False, poll_sec=2.0,
                        stall_sec=180, request_timeout=240)
    sm = load_regime()
    client = OpenCodeClient(BASE, model=settings.model, timeout=settings.request_timeout)
    rep = Reporter(journal_path=journal)
    driver = StatechartDriver(settings, sm, client, reporter=rep)
    try:
        outcome, end, _ = driver.run(
            "写一个Python函数 f(x)=x*3 保存到 e2e_triple.py 并运行确认", timeout_sec=300)
        assert outcome == Outcome.COMPLETE
    finally:
        rep.close()
    recs = Reporter(journal_path=journal).load()
    assert recs > 0
    assert any("node_enter" in line for line in
               open(journal, encoding="utf-8").readlines())


# -- real supervisor / drive stack (P0#2: real-worker correction ladder) --------

def test_real_drive_supervisor_no_false_stall(tmp_path):
    """The full one-stack (executor + process-external supervisor + reporter)
    must COMPLETE a real task with NO false stall, and the supervisor must share
    the one reporter journal (proving the watchdog is genuinely wired, not dead).
    """
    from regime_driver.app.reporter import Reporter
    from regime_driver.drive import Drive
    from regime_driver.infra.opencode import OpenCodeClient

    journal = tmp_path / "e2e-drive.jsonl"
    settings = Settings(base_url=BASE, monitor_enabled=False, poll_sec=2.0,
                        stall_sec=180, request_timeout=240)
    sm = load_regime()
    client = OpenCodeClient(BASE, model=settings.model, timeout=settings.request_timeout)
    rep = Reporter(journal_path=journal, project_id="drive")
    drv = Drive(settings, sm, client, rep, deadline_sec=600, stall_sec=180,
                meta_enabled=False)
    try:
        dr = drv.run("写一个Python函数 g(x)=x*4 保存到 e2e_quad.py 并运行确认")
        assert dr.outcome == Outcome.COMPLETE.value, (
            f"drive outcome={dr.outcome} supervisor={dr.supervisor}")
        assert dr.end == "wrap"
        assert dr.session_id is not None
        # supervisor ended because the workflow finished (not the deadline)
        assert dr.supervisor == "workflow_done"
    finally:
        rep.close()
    # supervisor ingested real worker SSE events into the SAME journal
    recs = [json.loads(l) for l in open(journal, encoding="utf-8").readlines()
            if l.strip()]
    assert any(r.get("kind") == "outcome" for r in recs)
    assert any(r.get("kind") == "worker" for r in recs)


def test_real_supervisor_meta_analyze_real_model():
    """Intelligent meta-analysis wired to a REAL model (P0#2).

    The supervisor asks an independent model to judge a session, parses the
    strict-JSON verdict and passes the deterministic gate. This proves the
    '元分析接真实模型' rung — the model genuinely reaches a gated verdict.
    """
    from regime_driver.supervisor import Supervisor

    settings = Settings(base_url=BASE)
    client = OpenCodeClient(BASE, model=settings.model, timeout=120)
    sid = client.create_session("e2e-meta")
    try:
        client.send_message(
            sid, "写一个会无限循环的程序并解释它为什么卡住", "developer")
        time.sleep(3)
        sup = Supervisor(
            client, session_id=sid, goal="e2e meta", meta_enabled=True,
            meta_model=settings.model)
        verdict = sup.meta_analyze()
        # a valid gated verdict: (verdict, action, confidence) triple
        assert verdict is not None
        v, action, conf = verdict
        assert v in ("normal", "stalled", "looping", "blocked", "error", "escalate")
        assert action in ("none", "nudge", "abort", "fallback_model",
                          "restart", "human")
        assert 0.0 <= conf <= 1.0
    finally:
        try:
            client.abort_session(sid)
            client.delete_session(sid)
        except Exception:
            pass


@pytest.mark.skipif(
    os.environ.get("REGIME_E2E_RESTART") != "1",
    reason="real container restart: set REGIME_E2E_RESTART=1 (disruptive)",
)
def test_real_supervisor_t1_restart_recovery():
    """T1 (worker unhealthy) -> L4 docker restart -> worker recovers.

    This is the real "restart" rung of the correction ladder, exercised against
    the ACTUAL worker container. It stops the worker, lets the supervisor detect
    the outage and issue `docker restart`, then asserts the worker comes back
    healthy. Gated behind REGIME_E2E_RESTART=1 so normal E2E runs don't disrupt
    the shared worker.
    """
    import subprocess
    import time

    from regime_driver.infra.opencode import OpenCodeClient
    from regime_driver.supervisor import Supervisor

    container = os.environ.get("REGIME_E2E_CONTAINER", "opencode-worker")
    client = OpenCodeClient(BASE, timeout=15)
    if not client.health():
        pytest.skip("worker not healthy; cannot run restart recovery")
    # stop the worker container (simulate an outage); handle the stale-shell
    # docker-group issue via the `sg docker` fallback
    stop_procs = [
        ["docker", "stop", container],
        ["sg", "docker", "-c", f"docker stop {container}"],
    ]
    stopped = False
    for cmd in stop_procs:
        proc = subprocess.run(cmd, capture_output=True)
        if proc.returncode == 0:
            stopped = True
            break
    assert stopped, "docker stop failed (need docker access)"
    try:
        # supervisor with T1 + container: first pass must detect unhealthy and restart
        sup = Supervisor(client, container=container, health_poll_sec=2.0,
                         stall_sec=60, deadline_sec=60)
        outcome = sup.run(once=True)
        # 'restart' means it detected unhealth and issued L4; or it may have
        # already recovered by the first health probe. Either way the worker must
        # eventually come back healthy.
        assert outcome in ("restart", "unhealthy", "complete")
    finally:
        # ensure the worker is back up (wait for healthy)
        deadline = time.time() + 120
        healthy = False
        while time.time() < deadline:
            try:
                if OpenCodeClient(BASE, timeout=10).health():
                    healthy = True
                    break
            except Exception:
                pass
            time.sleep(2)
        assert healthy, "worker did not recover after restart"
