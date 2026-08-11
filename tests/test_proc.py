"""Tests for the shared process-liveness helper (zombie-aware)."""

from __future__ import annotations

import os
import time

from regime_driver.infra.proc import _pid_state, pid_alive


def _spawn_zombie() -> int:
    """Fork a child that exits immediately; return its pid (now a zombie)."""
    pid = os.fork()
    if pid == 0:
        os._exit(0)
    # give the kernel a moment to reap the child into a zombie
    time.sleep(0.3)
    return pid


def test_pid_state_of_zombie_is_Z():
    pid = _spawn_zombie()
    try:
        assert _pid_state(pid) == "Z"
    finally:
        os.waitpid(pid, 0)


def test_pid_alive_false_for_zombie():
    # the regression this guards: os.kill(pid, 0) returns True for a zombie,
    # so a crashed background job looked permanently "running".
    pid = _spawn_zombie()
    try:
        assert os.kill(pid, 0) is None  # naive probe cannot see the zombie
        assert pid_alive(pid) is False  # our helper treats it as dead
    finally:
        os.waitpid(pid, 0)


def test_pid_alive_true_for_live_process():
    # our own current process is live and non-zombie
    assert pid_alive(os.getpid()) is True


def test_pid_alive_false_for_nonexistent_pid():
    # find a pid that does not exist (spawn then fully reap, reuse unlikely)
    pid = os.fork()
    if pid == 0:
        os._exit(0)
    os.waitpid(pid, 0)  # fully reaped -> pid gone
    assert pid_alive(pid) is False


def test_pid_alive_false_for_none():
    assert pid_alive(None) is False
    assert pid_alive(0) is False
