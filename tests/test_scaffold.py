"""regime scaffold tests (WORK_PLAN7 II)."""

from __future__ import annotations

from pathlib import Path

import pytest

from regime_driver.scaffold import DATA_DIR, ScaffoldResult, scaffold, scaffold_plan, templates_ready


def test_scaffold_plan_has_agents_and_skills(tmp_path):
    plan = scaffold_plan(tmp_path, assistants=False)
    dests = [str(c.dest.relative_to(tmp_path)) for c in plan]
    assert any(d.startswith("agents/reviewer.md") for d in dests)
    assert any(d.startswith("skills/design-philosophy/SKILL.md") for d in dests)
    assert all(not str(d).startswith("dialog-control-assistants") for d in dests)


def test_scaffold_accepts_str_target(tmp_path):
    """A plain string target must work (coerced to Path), not crash path arithmetic."""
    result = scaffold(str(tmp_path), assistants=True)
    assert isinstance(result, ScaffoldResult)
    assert (tmp_path / "agents" / "reviewer.md").is_file()
    assert (tmp_path / "skills" / "design-philosophy" / "SKILL.md").is_file()


def test_scaffold_plan_assistants(tmp_path):
    plan = scaffold_plan(tmp_path, assistants=True)
    dests = [str(c.dest.relative_to(tmp_path)) for c in plan]
    assert "agents/analyst.md" in dests
    assert "agents/advisor.md" in dests
    assert "agents/reviewer.md" in dests


def test_scaffold_writes_files(tmp_path):
    result = scaffold(tmp_path, assistants=True)
    assert isinstance(result, ScaffoldResult)
    assert (tmp_path / "agents" / "reviewer.md").is_file()
    assert (tmp_path / "agents" / "analyst.md").is_file()
    assert (tmp_path / "skills" / "design-philosophy" / "SKILL.md").is_file()
    assert len(result.copied) == len(result.plan) - len(result.skipped)
    assert result.skipped == []


def test_scaffold_idempotent_keeps_existing(tmp_path):
    first = scaffold(tmp_path, assistants=True)
    written = (tmp_path / "agents" / "reviewer.md")
    written.write_text("custom user content", encoding="utf-8")

    second = scaffold(tmp_path, assistants=True)
    assert written.read_text(encoding="utf-8") == "custom user content"
    assert second.skipped
    assert not second.copied


def test_scaffold_force_overwrites(tmp_path):
    scaffold(tmp_path, assistants=False)
    written = (tmp_path / "agents" / "reviewer.md")
    written.write_text("old", encoding="utf-8")
    result = scaffold(tmp_path, assistants=False, force=True)
    assert result.copied
    assert (tmp_path / "agents" / "reviewer.md").read_text(encoding="utf-8") != "old"


def test_scaffold_dry_run_writes_nothing(tmp_path):
    result = scaffold(tmp_path, assistants=True, dry_run=True)
    assert result.plan
    assert not result.copied
    assert not (tmp_path / "agents").exists()
    assert not (tmp_path / "skills").exists()


def test_scaffold_copies_are_self_contained_not_symlinks(tmp_path):
    scaffold(tmp_path, assistants=True)
    # no symlink to the source package: a fresh user can delete the repo
    for dest in (tmp_path / "agents").iterdir():
        assert not dest.is_symlink()


def test_templates_ready_ok():
    res = templates_ready()
    assert res["ok"] is True
    assert len(res["checks"]) == 3


def test_scaffold_sources_exist_in_package():
    assert (DATA_DIR / "agents" / "reviewer.md").is_file()
    assert (DATA_DIR / "skills" / "code-review" / "SKILL.md").is_file()
    assert (DATA_DIR / "dialog-control-assistants" / "analyst.md").is_file()


def test_cli_scaffold_dry_run_json(tmp_path):
    from typer.testing import CliRunner

    from regime_driver.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["scaffold", "--target", str(tmp_path), "--dry-run", "--json"])
    assert result.exit_code == 0, result.output
    import json
    data = json.loads(result.output)
    assert data["dry_run"] is True
    assert data["plan"]
    assert not (tmp_path / "agents").exists()


def test_cli_scaffold_writes_json(tmp_path):
    from typer.testing import CliRunner

    from regime_driver.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["scaffold", "--target", str(tmp_path), "--assistants", "--json"])
    assert result.exit_code == 0, result.output
    import json
    data = json.loads(result.output)
    assert (tmp_path / "agents" / "analyst.md").is_file()
    assert (tmp_path / "skills" / "design-philosophy" / "SKILL.md").is_file()
    assert data["assistants"] is True
