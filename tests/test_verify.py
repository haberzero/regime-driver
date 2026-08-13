"""Tests for the runtime verification runner (WORK_PLAN13 verify hook)."""

from __future__ import annotations

from regime_driver.app.verify import (
    render_verify_prompt_block,
    run_verify,
)


def test_run_verify_ok():
    r = run_verify("echo hello", container="opencode-worker", timeout=10.0)
    assert r.ok and r.rc == 0
    assert "hello" in r.stdout_tail


def test_run_verify_failure():
    r = run_verify("exit 3", container="opencode-worker", timeout=10.0)
    assert not r.ok and r.rc == 3
    assert r.failed


def test_run_verify_container_substitution():
    r = run_verify("echo {container}", container="my-worker", timeout=10.0)
    assert r.ok
    assert "my-worker" in r.stdout_tail


def test_run_verify_missing_command_not_ok():
    r = run_verify("definitely-not-a-command-xyz", container="c", timeout=10.0)
    assert r.failed


def test_render_ok_block_has_no_warning():
    from regime_driver.app.verify import VerifyResult
    res = VerifyResult(ok=True, rc=0, stdout_tail="63 passed",
                       stderr_tail="", elapsed=0.5, timed_out=False)
    block = render_verify_prompt_block(res, "pytest -q")
    assert "63 passed" in block
    assert "未通过" not in block


def test_render_failed_block_warns_blocking():
    from regime_driver.app.verify import VerifyResult
    res = VerifyResult(ok=False, rc=1, stdout_tail="3 failed",
                       stderr_tail="", elapsed=0.5, timed_out=False)
    block = render_verify_prompt_block(res, "pytest -q")
    assert "3 failed" in block
    assert "blocking" in block  # must not advance past failing runtime evidence
