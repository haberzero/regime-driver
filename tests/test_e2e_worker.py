"""Real-worker E2E regression (T-A).

Drives the ACTUAL opencode worker container over HTTP (the same mechanism
regime-driver uses in production) and asserts a full flow COMPLETES. This is the
"execution" verification — it proves the worker can carry a real task through
understand→…→wrap. It is gated behind REGIME_E2E=1 and a healthy worker so the
normal unit suite stays fast and offline; run explicitly for real verification:

    REGIME_E2E=1 conda run -n regime-driver python -m pytest tests/test_e2e_worker.py -q
"""

from __future__ import annotations

import os

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
