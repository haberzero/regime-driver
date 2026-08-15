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
    # host-mode opencode main config (model providers, {env:...} placeholders)
    assert (tmp_path / "opencode.json").is_file()
    # config reference (single source of truth) ships too
    assert (tmp_path / "config.example.toml").is_file()
    # A-route dialog-control carrier: plugin + dialog-control agent + package.json
    assert (tmp_path / "plugins" / "regime-dialog-control.js").is_file()
    assert (tmp_path / "agents" / "dialog-control.md").is_file()
    assert (tmp_path / "package.json").is_file()
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


def test_scaffold_writes_manifest(tmp_path):
    """Deployment manifest: scaffold must record what it deployed (for uninstall)."""
    from regime_driver.scaffold import load_manifest
    scaffold(tmp_path)
    m = load_manifest(tmp_path)
    assert m is not None
    assert m["schema"] == 1
    assert len(m["files"]) >= 1
    # the plugin + dialog-control agent are tracked
    paths = [f["path"] for f in m["files"]]
    assert any("plugins/regime-dialog-control.js" in p for p in paths)
    assert any("agents/dialog-control.md" in p for p in paths)
    # manifest covers plan even when idempotent (existing files still tracked)
    scaffold(tmp_path)  # re-run over existing files
    m2 = load_manifest(tmp_path)
    assert len(m2["files"]) == len(m["files"])


def test_uninstall_removes_only_unchanged_files(tmp_path):
    """Safe uninstall: removes regime files, KEEPS user-modified ones."""
    from regime_driver.scaffold import check_deployed, uninstall
    scaffold(tmp_path)
    # user modifies one agent file
    modified = tmp_path / "agents" / "dialog-control.md"
    modified.write_text(modified.read_text() + "\n# user edit\n", encoding="utf-8")

    d = check_deployed(tmp_path)
    assert d["deployed"] and d["ok"] is False
    assert len(d["modified"]) == 1

    # dry-run: the modified file is listed as kept, not removed
    u = uninstall(tmp_path, dry_run=True)
    assert len(u["kept_modified"]) == 1
    assert len(u["removed"]) >= 1

    # real uninstall: modified file survives, others gone, manifest removed
    u2 = uninstall(tmp_path)
    assert modified.is_file(), "user-modified file must be kept"
    assert not (tmp_path / ".regime-deployed.json").exists()
    assert not (tmp_path / "plugins" / "regime-dialog-control.js").exists()


def test_uninstall_no_manifest_is_noop(tmp_path):
    from regime_driver.scaffold import uninstall
    res = uninstall(tmp_path)
    assert res["manifest"] is False


def test_check_plugin_ok_on_packaged():
    """The packaged plugin must carry the v1 default-export shape opencode's
    auto-scan loader reliably detects."""
    from regime_driver.scaffold import DATA_DIR, check_plugin
    res = check_plugin()
    assert res["ok"] is True, res
    assert "regime-dialog-control.js" in res["detail"]


def test_check_plugin_missing_file(tmp_path):
    from regime_driver.scaffold import check_plugin
    res = check_plugin(tmp_path)  # empty dir -> no plugin
    assert res["ok"] is False
    assert "not deployed" in res["detail"]


def test_check_plugin_rejects_named_export_only(tmp_path):
    """A plugin file that only has a named export (no v1 default export) must
    be flagged: opencode may silently skip it on the auto-scan path."""
    from regime_driver.scaffold import check_plugin
    d = tmp_path / "plugins"
    d.mkdir()
    (d / "regime-dialog-control.js").write_text(
        "export const DialogControlPlugin = async () => ({ tool: {} })\n",
        encoding="utf-8",
    )
    res = check_plugin(d)
    assert res["ok"] is False
    assert "export default" in res["detail"]


def test_check_plugin_accepts_deployed_copy(tmp_path):
    """The actually-deployed file (scaffold output) must pass the loadability
    check, not just the packaged copy."""
    from regime_driver.scaffold import check_plugin, scaffold
    scaffold(tmp_path)
    res = check_plugin(tmp_path / "plugins")
    assert res["ok"] is True, res


# ---------------------------------------------------------------------------
# workspace mode (project-local .opencode/ — the recommended path)
# ---------------------------------------------------------------------------

def test_scaffold_plan_workspace_uses_singular_agent_dir(tmp_path):
    """Workspace mode must use `agent/` (singular — the project-level opencode
    convention), not `agents/` (the global convention)."""
    from regime_driver.scaffold import scaffold_plan
    plan = scaffold_plan(tmp_path, workspace=True)
    dests = [str(c.dest.relative_to(tmp_path)) for c in plan]
    assert any(d.startswith("agent/dialog-control.md") for d in dests), dests
    assert any(d.startswith("agent/reviewer.md") for d in dests), dests
    # no global-convention agents/ dir in workspace mode
    assert not any(d.startswith("agents/") for d in dests), dests


def test_scaffold_plan_workspace_ships_handbook_no_config(tmp_path):
    """Workspace mode ships the agent handbook (self-serve configuration inside
    opencode) and must NOT write opencode.json / config.example.toml (no project
    pollution)."""
    from regime_driver.scaffold import scaffold_plan
    plan = scaffold_plan(tmp_path, workspace=True)
    dests = [str(c.dest.relative_to(tmp_path)) for c in plan]
    assert "agent-handbook.md" in dests, dests
    assert "opencode.json" not in dests, dests
    assert "config.example.toml" not in dests, dests
    # plugin + skills + package.json still ship
    assert "plugins/regime-dialog-control.js" in dests, dests
    assert any(d.startswith("skills/") for d in dests), dests
    assert "package.json" in dests, dests


def test_scaffold_workspace_writes_into_opencode_dir(tmp_path):
    from regime_driver.scaffold import scaffold
    result = scaffold(tmp_path / ".opencode", workspace=True)
    assert (tmp_path / ".opencode" / "plugins" / "regime-dialog-control.js").is_file()
    assert (tmp_path / ".opencode" / "agent" / "dialog-control.md").is_file()
    assert (tmp_path / ".opencode" / "agent-handbook.md").is_file()
    assert (tmp_path / ".opencode" / ".regime-deployed.json").is_file()
    # no pollution outside .opencode
    assert not (tmp_path / "opencode.json").exists()
    assert not (tmp_path / "config.example.toml").exists()


def test_scaffold_workspace_manifest_and_uninstall(tmp_path):
    """Workspace deployment must be removable by `uninstall` on the .opencode dir
    (the CLI composes `<dir>/.opencode` before calling)."""
    from regime_driver.scaffold import check_deployed, scaffold, uninstall
    target = tmp_path / ".opencode"
    scaffold(target, workspace=True)
    d = check_deployed(target)
    assert d["deployed"] and d["ok"] is True
    # user modifies one file -> uninstall keeps it
    modified = target / "agent-handbook.md"
    modified.write_text(modified.read_text(encoding="utf-8") + "\n# user edit\n", encoding="utf-8")
    u = uninstall(target)
    assert modified.is_file(), "user-modified file must be kept"
    assert not (target / "plugins" / "regime-dialog-control.js").exists()
    assert not (target / ".regime-deployed.json").exists()


def test_cli_scaffold_workspace_json(tmp_path):
    from typer.testing import CliRunner

    from regime_driver.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["scaffold", "--workspace", str(tmp_path), "--json"])
    assert result.exit_code == 0, result.output
    import json
    data = json.loads(result.output)
    assert (tmp_path / ".opencode" / "agent" / "dialog-control.md").is_file()
    assert (tmp_path / ".opencode" / "plugins" / "regime-dialog-control.js").is_file()
    # no global pollution
    assert not (tmp_path / "opencode.json").exists()


def test_cli_scaffold_target_workspace_mutually_exclusive(tmp_path):
    from typer.testing import CliRunner

    from regime_driver.cli import app

    runner = CliRunner()
    result = runner.invoke(app, ["scaffold", "--target", str(tmp_path),
                                 "--workspace", str(tmp_path)])
    assert result.exit_code == 1
    assert "mutually exclusive" in result.output


def test_cli_uninstall_workspace(tmp_path):
    from typer.testing import CliRunner

    from regime_driver.cli import app

    runner = CliRunner()
    r1 = runner.invoke(app, ["scaffold", "--workspace", str(tmp_path), "--json"])
    assert r1.exit_code == 0, r1.output
    assert (tmp_path / ".opencode" / "plugins" / "regime-dialog-control.js").is_file()
    r2 = runner.invoke(app, ["uninstall", "--workspace", str(tmp_path), "--json"])
    assert r2.exit_code == 0, r2.output
    assert not (tmp_path / ".opencode" / "plugins" / "regime-dialog-control.js").exists()
    assert not (tmp_path / ".opencode" / ".regime-deployed.json").exists()


def test_cli_workspace_accepts_dir_already_named_opencode(tmp_path):
    """W1: passing a dir that already IS `.opencode` must not compose
    `.opencode/.opencode` (idempotent target resolution)."""
    from typer.testing import CliRunner

    from regime_driver.cli import app

    runner = CliRunner()
    ws = tmp_path / ".opencode"
    r1 = runner.invoke(app, ["scaffold", "--workspace", str(ws), "--json"])
    assert r1.exit_code == 0, r1.output
    # files land directly in ws (not ws/.opencode)
    assert (ws / "plugins" / "regime-dialog-control.js").is_file()
    assert not (ws / ".opencode").exists()
    # uninstall on the same dir works
    r2 = runner.invoke(app, ["uninstall", "--workspace", str(ws), "--json"])
    assert r2.exit_code == 0, r2.output
    assert not (ws / "plugins" / "regime-dialog-control.js").exists()


def test_uninstall_skips_tampered_manifest_outside_target(tmp_path):
    """W2: a manifest entry pointing OUTSIDE the deployment target must never be
    deleted (defense against a tampered manifest)."""
    from regime_driver.scaffold import MANIFEST_NAME, scaffold, uninstall
    target = tmp_path / ".opencode"
    scaffold(target, workspace=True)
    # tamper the manifest: add an entry pointing at a file outside the target
    outside = tmp_path / "outside.txt"
    outside.write_text("do not delete", encoding="utf-8")
    manifest_path = target / MANIFEST_NAME
    import json
    m = json.loads(manifest_path.read_text(encoding="utf-8"))
    m["files"].append({"path": str(outside), "sha256": __import__("hashlib").sha256(
        outside.read_bytes()).hexdigest()})
    manifest_path.write_text(json.dumps(m), encoding="utf-8")

    u = uninstall(target)
    assert outside.is_file(), "outside file must never be deleted"
    assert str(outside) in u["kept_modified"], "outside path must be flagged as kept"
    # regime's own files inside target are still removed
    assert not (target / "plugins" / "regime-dialog-control.js").exists()
