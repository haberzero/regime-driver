"""Session-cleanup policy tests (L2 resource governance, WORK_PLAN6 L2)."""

from __future__ import annotations

import json

import pytest

from regime_driver.app.session_cleanup import (
    CleanupPolicy,
    CleanupResult,
    plan_cleanup,
    run_cleanup,
)


NOW = 1_700_000_000.0  # wall-clock seconds (time.time() scale)


def _sessions(n: int, *, age_sec: int = 3600, prefix: str = "ses") -> list[dict]:
    created = int(NOW - age_sec) * 1000  # millis, matching opencode time.created
    return [{"id": f"{prefix}_{i}", "time": {"created": created}} for i in range(n)]


def test_policy_disabled_by_default():
    p = CleanupPolicy.from_config(None)
    assert p.enabled is False
    p2 = CleanupPolicy.from_config("not json")
    assert p2.enabled is False
    p3 = CleanupPolicy.from_config("[]")
    assert p3.enabled is False
    p4 = CleanupPolicy.from_config("{}")
    assert p4.enabled is False


def test_policy_parses_valid_json():
    p = CleanupPolicy.from_config('{"max_sessions": 100, "min_age_sec": 3600, "only_idle": false}')
    assert p.enabled is True
    assert p.max_sessions == 100
    assert p.min_age_sec == 3600
    assert p.only_idle is False


def test_policy_defaults_only_idle_true():
    p = CleanupPolicy.from_config('{"max_sessions": 50}')
    assert p.only_idle is True
    assert p.min_age_sec == 0


def test_policy_rejects_bool_max_sessions():
    """bool is an int in Python — a JSON `"max_sessions": true` must NOT enable
    a near-total teardown (code-review warning)."""
    p = CleanupPolicy.from_config('{"max_sessions": true}')
    assert p.enabled is False
    p2 = CleanupPolicy.from_config('{"max_sessions": 5, "min_age_sec": true}')
    assert p2.enabled is True
    assert p2.min_age_sec == 0  # bool coerced to 0, not 1


def test_plan_cleans_oldest_by_age_not_insertion():
    """Oldest-first must follow actual age, not list order."""
    now = NOW
    sessions = [
        {"id": "old", "time": {"created": int(now - 7200) * 1000}},
        {"id": "mid", "time": {"created": int(now - 3600) * 1000}},
        {"id": "new", "time": {"created": int(now - 100) * 1000}},
        {"id": "n2", "time": {"created": int(now - 200) * 1000}},
        {"id": "n3", "time": {"created": int(now - 300) * 1000}},
    ]
    p = CleanupPolicy.from_config('{"max_sessions": 2}')
    res = plan_cleanup(sessions, p, now=now)
    # delete 3 oldest: old(7200), mid(3600), n3(300) — NOT by insertion order
    assert res.deleted_count == 3
    assert res.deleted[0] == "old"
    assert res.deleted[1] == "mid"
    assert res.deleted[2] == "n3"


def test_plan_cleans_oldest_excess():
    """120 sessions, cap 100 → delete 20 oldest."""
    sessions = _sessions(120, age_sec=7200)
    p = CleanupPolicy.from_config('{"max_sessions": 100}')
    res = plan_cleanup(sessions, p, now=NOW)
    assert isinstance(res, CleanupResult)
    assert res.deleted_count == 20
    assert len(res.deleted) == 20
    # oldest deleted: first created (ses_0..ses_19)
    assert res.deleted[0] == "ses_0"
    assert res.deleted[-1] == "ses_19"


def test_plan_noop_under_cap():
    sessions = _sessions(50)
    p = CleanupPolicy.from_config('{"max_sessions": 100}')
    res = plan_cleanup(sessions, p)
    assert res.deleted_count == 0
    assert res.deleted == []


def test_plan_skips_busy():
    sessions = _sessions(120, age_sec=7200)
    p = CleanupPolicy.from_config('{"max_sessions": 100}')
    res = plan_cleanup(sessions, p, now=NOW,
                       busy_ids={"ses_0", "ses_1"})
    # busy ones are never deleted; delete the next 20 oldest eligible
    assert "ses_0" not in res.deleted
    assert "ses_1" not in res.deleted
    assert res.deleted_count == 20
    assert res.skipped_busy == 2


def test_plan_respects_min_age():
    sessions = _sessions(120, age_sec=600)  # all younger than 3600
    p = CleanupPolicy.from_config('{"max_sessions": 100, "min_age_sec": 3600}')
    res = plan_cleanup(sessions, p, now=NOW)
    assert res.deleted_count == 0
    assert res.skipped_young == 120


def test_run_cleanup_deletes_via_client():
    class FakeClient:
        def __init__(self):
            self.deleted = []

        def delete_session(self, sid):
            self.deleted.append(sid)

    sessions = _sessions(120, age_sec=7200)
    p = CleanupPolicy.from_config('{"max_sessions": 100}')
    client = FakeClient()
    res = run_cleanup(client, sessions, p, now=NOW)
    assert len(client.deleted) == 20
    assert res.deleted == client.deleted


def test_run_cleanup_best_effort_on_error():
    class FlakyClient:
        def __init__(self):
            self.deleted = []

        def delete_session(self, sid):
            if sid == "ses_3":
                raise RuntimeError("boom")
            self.deleted.append(sid)

    sessions = _sessions(120, age_sec=7200)
    p = CleanupPolicy.from_config('{"max_sessions": 100}')
    res = run_cleanup(FlakyClient(), sessions, p, now=NOW)
    assert res.deleted_count == 19  # the failing one is skipped
    assert "ses_3" not in res.deleted


def test_cli_sessions_cleanup_gate_and_delete():
    """--cleanup is CLEAN-gated and applies the policy against a fake client."""
    from typer.testing import CliRunner

    import regime_driver.cli as cli
    from regime_driver.cli import app

    runner = CliRunner()

    class _Fake:
        def __init__(self, n):
            self.sessions = _sessions(n, age_sec=7200)
            self.busy = set()

        def list_sessions(self):
            return self.sessions

        def session_status_map(self):
            return {sid: "idle" for sid in self.busy}

        def delete_session(self, sid):
            self.sessions = [s for s in self.sessions if s.get("id") != sid]

    fake = _Fake(120)
    original = cli.OpenCodeClient
    cli.OpenCodeClient = lambda base, **kw: fake  # noqa: E731
    try:
        res = runner.invoke(app, ["sessions", "--cleanup", '{"max_sessions": 100}',
                                  "--json", "--perm", "clean"])
    finally:
        cli.OpenCodeClient = original
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["deleted_count"] == 20
    assert len(fake.sessions) == 100


def test_cli_sessions_cleanup_low_perm_denied(monkeypatch):
    from typer.testing import CliRunner

    from regime_driver.cli import app

    monkeypatch.setenv("REGIME_PERMISSION_CEILING", "read")
    res = CliRunner().invoke(app, ["sessions", "--cleanup", '{"max_sessions": 5}',
                                   "--json"])
    assert res.exit_code == 1
    assert "permission denied" in res.output
