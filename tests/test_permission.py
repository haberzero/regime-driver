"""Tests for the fine-grained permission policy (infra/permission.py)."""

from __future__ import annotations

import pytest

from regime_driver.infra.permission import (
    PermissionDenied,
    PermissionLevel,
    classify,
    clamp,
    from_dialog_control,
    require,
)


def test_classify_read_commands() -> None:
    assert classify(["status"]) == PermissionLevel.READ
    assert classify(["sessions"]) == PermissionLevel.READ
    assert classify(["events", "--ledger", "x"]) == PermissionLevel.READ
    assert classify(["session", "reply", "abc"]) == PermissionLevel.READ
    assert classify(["validate"]) == PermissionLevel.READ
    assert classify(["gate", "{}"]) == PermissionLevel.READ
    assert classify(["job", "list"]) == PermissionLevel.READ
    assert classify(["job", "status", "x"]) == PermissionLevel.READ


def test_classify_interact() -> None:
    assert classify(["session", "send", "abc", "hello"]) == PermissionLevel.INTERACT


def test_classify_run() -> None:
    assert classify(["run", "task"]) == PermissionLevel.RUN
    assert classify(["run-many", "a", "b"]) == PermissionLevel.RUN
    assert classify(["drive", "task"]) == PermissionLevel.RUN
    assert classify(["task", "submit", "x"]) == PermissionLevel.RUN
    assert classify(["run", "task", "--async"]) == PermissionLevel.RUN


def test_classify_clean() -> None:
    assert classify(["sessions", "--clean"]) == PermissionLevel.CLEAN
    assert classify(["sessions", "--kill", "abc"]) == PermissionLevel.CLEAN
    assert classify(["supervisor"]) == PermissionLevel.CLEAN
    assert classify(["task", "stop", "x"]) == PermissionLevel.CLEAN
    assert classify(["task", "clean", "x"]) == PermissionLevel.CLEAN
    assert classify(["task", "list"]) == PermissionLevel.READ


def test_require_ordering() -> None:
    require(PermissionLevel.READ, PermissionLevel.READ)
    require(PermissionLevel.CLEAN, PermissionLevel.READ)
    require(PermissionLevel.RUN, PermissionLevel.INTERACT)
    with pytest.raises(PermissionDenied):
        require(PermissionLevel.READ, PermissionLevel.RUN)
    with pytest.raises(PermissionDenied):
        require(PermissionLevel.INTERACT, PermissionLevel.CLEAN)


def test_from_dialog_control() -> None:
    assert from_dialog_control(False) == PermissionLevel.READ
    assert from_dialog_control(True) == PermissionLevel.CLEAN


def test_clamp_cannot_self_elevate() -> None:
    # ceiling=run: a self-declared clean is clamped down to run
    assert clamp(PermissionLevel.CLEAN, PermissionLevel.RUN) == PermissionLevel.RUN
    assert clamp(PermissionLevel.RUN, PermissionLevel.RUN) == PermissionLevel.RUN
    # lowering within the ceiling is allowed
    assert clamp(PermissionLevel.READ, PermissionLevel.RUN) == PermissionLevel.READ
    # full ceiling passes everything
    assert clamp(PermissionLevel.CLEAN, PermissionLevel.CLEAN) == PermissionLevel.CLEAN


def test_ceiling_rejects_run_when_read() -> None:
    # an operator with ceiling=read cannot run (RUN required), even claiming clean
    with pytest.raises(PermissionDenied):
        require(clamp(PermissionLevel.CLEAN, PermissionLevel.READ),
                classify(["run", "x"]))

