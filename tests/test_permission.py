"""Tests for the fine-grained permission policy (infra/permission.py)."""

from __future__ import annotations

import pytest

from regime_driver.infra.permission import (
    PermissionDenied,
    PermissionLevel,
    classify,
    from_god_dialog,
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
    # async does not escalate
    assert classify(["run", "task", "--async"]) == PermissionLevel.RUN


def test_classify_clean() -> None:
    assert classify(["sessions", "--clean"]) == PermissionLevel.CLEAN
    assert classify(["sessions", "--kill", "abc"]) == PermissionLevel.CLEAN


def test_require_ordering() -> None:
    require(PermissionLevel.READ, PermissionLevel.READ)
    require(PermissionLevel.CLEAN, PermissionLevel.READ)
    require(PermissionLevel.RUN, PermissionLevel.INTERACT)
    with pytest.raises(PermissionDenied):
        require(PermissionLevel.READ, PermissionLevel.RUN)
    with pytest.raises(PermissionDenied):
        require(PermissionLevel.INTERACT, PermissionLevel.CLEAN)


def test_from_god_dialog() -> None:
    assert from_god_dialog(False) == PermissionLevel.READ
    assert from_god_dialog(True) == PermissionLevel.CLEAN
