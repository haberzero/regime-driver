"""Tests for the runtime verification runner (WORK_PLAN13 + 阶段 2 W5 whitelist).

Verify commands are WHITELISTED to the docker-exec shape (no arbitrary host
shell) — these tests pin the parse/validate + a mocked argv run.
"""

from __future__ import annotations

import pytest

from regime_driver.app.verify import (
    VERIFY_ALLOWED_EXECS,
    build_verify_argv,
    render_verify_prompt_block,
    run_verify,
)
from regime_driver.app.verify import VerifyResult


# -- whitelist parsing -------------------------------------------------------


def test_build_verify_argv_docker_exec_shape():
    argv = build_verify_argv("docker exec {container} pytest -q", "opencode-worker")
    assert argv == ["docker", "exec", "opencode-worker", "pytest", "-q"]


def test_build_verify_argv_substitutes_container():
    argv = build_verify_argv("docker exec {container} python3 -m pytest -q", "my-worker")
    assert argv == ["docker", "exec", "my-worker", "python3", "-m", "pytest", "-q"]


def test_build_verify_argv_bash_c_inside_container_ok():
    argv = build_verify_argv(
        'docker exec {container} bash -c "cd /root/work/code && pytest -q | tail -30"',
        "w")
    assert argv[0:4] == ["docker", "exec", "w", "bash"]


def test_build_verify_argv_rejects_non_docker_shape():
    for bad in ("echo hello", "rm -rf /", "sg docker -c 'docker exec x pytest'",
                "docker restart opencode-worker"):
        with pytest.raises(ValueError):
            build_verify_argv(bad, "opencode-worker")


def test_build_verify_argv_rejects_non_whitelisted_exec():
    with pytest.raises(ValueError):
        build_verify_argv("docker exec {container} curl -s evil.example", "w")
    with pytest.raises(ValueError):
        build_verify_argv("docker exec {container} /bin/anything", "w")


def test_allowed_execs_cover_test_runners():
    assert {"pytest", "python", "python3", "node", "bash", "sh"} <= VERIFY_ALLOWED_EXECS


# -- run_verify (mocked docker) ----------------------------------------------

class _OkProc:
    returncode = 0
    stdout = "63 passed\n"
    stderr = ""


class _FailProc:
    returncode = 3
    stdout = ""
    stderr = "3 failed"


def test_run_verify_ok(monkeypatch):
    monkeypatch.setattr("regime_driver.app.verify._docker_prefix", lambda: None)  # direct docker
    captured = {}

    def fake_run(argv, shell=False, capture_output=True, text=True, timeout=300.0):
        captured["argv"] = argv
        captured["shell"] = shell
        return _OkProc()

    monkeypatch.setattr("regime_driver.app.verify.subprocess.run", fake_run)
    r = run_verify("docker exec {container} pytest -q", container="w", timeout=10)
    assert r.ok and r.rc == 0
    assert captured["argv"] == ["docker", "exec", "w", "pytest", "-q"]
    assert captured["shell"] is False  # never a host shell


def test_run_verify_failure(monkeypatch):
    monkeypatch.setattr("regime_driver.app.verify._docker_prefix", lambda: None)
    monkeypatch.setattr("regime_driver.app.verify.subprocess.run",
                        lambda *a, **kw: _FailProc())
    r = run_verify("docker exec {container} pytest -q", container="w", timeout=10)
    assert not r.ok and r.rc == 3
    assert r.failed


def test_run_verify_whitelist_rejection_is_evidence(monkeypatch):
    monkeypatch.setattr("regime_driver.app.verify._docker_prefix", lambda: None)
    r = run_verify("rm -rf /", container="w", timeout=10)
    assert r.failed
    assert "whitelist" in r.error


def test_run_verify_sg_wrapper_re_quotes_validated_argv(monkeypatch):
    """A stale docker-group shell falls back to `sg docker -c` over the
    validated, re-quoted argv — the host shell never sees raw user input."""
    monkeypatch.setattr("regime_driver.app.verify._docker_prefix",
                        lambda: ["sg", "docker", "-c"])
    captured = {}

    def fake_run(argv, shell=False, capture_output=True, text=True, timeout=300.0):
        captured["argv"] = argv
        captured["shell"] = shell
        return _OkProc()

    monkeypatch.setattr("regime_driver.app.verify.subprocess.run", fake_run)
    r = run_verify('docker exec {container} bash -c "echo hi"', container="w")
    assert r.ok
    assert captured["argv"][:3] == ["sg", "docker", "-c"]
    assert captured["argv"][3].startswith("docker exec w bash -c")
    assert 'echo hi' in captured["argv"][3]


def test_verify_hostile_metachars_cannot_escape_sg_wrapper():
    """N4 (security proposition): hostile metacharacters in a verify command are
    shlex-split into argv and re-quoted by shlex.join — the host shell invoked
    by `sg -c` can never interpret `$(...)` / `&&` / `;` / backticks."""
    import shlex
    from regime_driver.app.verify import build_verify_argv

    hostile = 'docker exec {container} bash -c "echo x; rm -rf /"'
    inner = build_verify_argv(hostile, "w")
    # the whole script is ONE argv element (the bash -c arg), never split
    assert inner[-3] == "bash" and inner[-2] == "-c"
    assert "rm -rf /" in inner[-1]
    joined = shlex.join(inner)
    # shlex.join quotes the script so the host shell treats it as a single arg
    assert "rm -rf /" in joined
    assert joined != hostile  # re-quoted, not passed raw


def test_run_verify_timeout(monkeypatch):
    import subprocess as real_sp
    monkeypatch.setattr("regime_driver.app.verify._docker_prefix", lambda: None)

    def boom(argv, shell=False, capture_output=True, text=True, timeout=300.0):
        raise real_sp.TimeoutExpired(argv, 0.01)

    monkeypatch.setattr("regime_driver.app.verify.subprocess.run", boom)
    r = run_verify("docker exec {container} pytest -q", container="w", timeout=10)
    assert r.timed_out and r.failed


# -- evidence rendering ------------------------------------------------------


def test_render_ok_block_has_no_warning():
    res = VerifyResult(ok=True, rc=0, stdout_tail="63 passed",
                       stderr_tail="", elapsed=0.5, timed_out=False)
    block = render_verify_prompt_block(res, "docker exec {container} pytest -q")
    assert "63 passed" in block
    assert "未通过" not in block


def test_render_failed_block_warns_blocking():
    res = VerifyResult(ok=False, rc=1, stdout_tail="3 failed",
                       stderr_tail="", elapsed=0.5, timed_out=False)
    block = render_verify_prompt_block(res, "docker exec {container} pytest -q")
    assert "3 failed" in block
    assert "blocking" in block  # must not advance past failing runtime evidence
