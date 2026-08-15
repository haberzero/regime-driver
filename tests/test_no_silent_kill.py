"""Fail-safe default policy for wall-clock kill switches.

Guard against "silent task-killer" defaults: anything that kills a running
task by wall clock must be OFF by default or generous enough that a long but
healthy phase/run can never be cut by accident. Liveness-based mechanisms
(SSE watchdog) stay ON by default — they only act on genuine stalls.
"""

from __future__ import annotations

from regime_driver.infra.settings import Settings
from regime_driver.infra.opencode import OpenCodeClient


def test_wall_clock_killers_default_off():
    """No wall-clock kill without an explicit deadline.

    Regression: default_deadline_sec used to default to 600s (killing any
    phase >10min even while streaming) and max_driver_wait_sec to 3600s
    (killing any run >1h without --deadline). Both must default to None.
    """
    s = Settings()
    assert s.default_deadline_sec is None, (
        "per-phase wall-clock deadline must default OFF; the SSE-liveness "
        "watchdog is the stall backstop")
    assert s.max_driver_wait_sec is None, (
        "whole-run wall-clock cap must default OFF without an explicit deadline")


def test_liveness_watchdog_stays_on_by_default():
    """The genuine stall backstop (SSE liveness) remains active by default."""
    s = Settings()
    assert s.stall_sec >= 1
    assert s.monitor_poll_sec >= 0.1


def test_message_post_timeout_is_generous():
    """A message POST blocks until the turn completes; a slow long generation
    (long review/implementation) must never be cut by a tight default."""
    s = Settings()
    assert s.request_timeout >= 300.0
    # bare client construction must not silently downgrade the cap
    assert OpenCodeClient("http://x:4097").timeout >= 300.0


def test_reviewer_retry_default_aligned_with_settings():
    """Class-level retry default must not diverge from the settings default
    (a bare-constructed Reviewer must behave like the settings-driven one)."""
    from regime_driver.app.reviewer import Reviewer
    s = Settings()
    assert Reviewer.__dataclass_fields__["max_retries"].default == s.max_reviewer_retries


def test_anti_runaway_caps_stay_configurable():
    """Anti-runaway caps (not kill-on-healthy-work) remain present and sane."""
    s = Settings()
    assert s.max_total_nodes >= 50
    assert s.max_reviewer_retries >= 3
