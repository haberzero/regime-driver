"""regime scaffold: one-shot deployment of the packaged official templates.

The distributed wheel ships the templates under ``regime_driver/data/`` (skills,
agents, dialog-control-assistant subagents, docker recipes, regime.json). ``scaffold`` copies
them to an opencode config target (default ``~/.config/opencode``) so a fresh
user does not need to clone the source repository.

Two modes (``workspace=`` flag):

- **global** (default): deploy into a global opencode config root:
  - agents   → <target>/agents/       (developer/reviewer templates)
  - skills   → <target>/skills/       (the runtime skills the flows reference)
  - plugins/ → <target>/plugins/      (regime-dialog-control.js — the A-route plugin that
                                       lets a HOST opencode be the primary dialog; opencode
                                       auto-loads local plugins here)
  - agents/dialog-control.md → <target>/agents/  (the dialog-control agent, auto-discovered)
  - package.json → <target>/package.json         (plugin SDK dep; opencode auto `bun install`)
  - opencode.json → <target>/opencode.json  (model providers; host-mode without docker)
  - config.example.toml → <target>/config.example.toml  (config reference, single truth)
  - --assistants    → also copies the dialog-control-assistant subagents (analyst/advisor/reviewer)
             → <target>/agents/

- **workspace** (recommended): deploy into a project-local ``<dir>/.opencode/`` so
  only that workspace's opencode sessions are affected:
  - ``agent/`` (singular — the project-level opencode convention) instead of ``agents/``
  - ``skills/`` (``.opencode/skills/`` is the project-level skills path opencode discovers)
  - ``plugins/``, ``package.json`` as in global mode
  - ``agent-handbook.md`` — the operator manual, deployed with the workspace so the
    user can read it inside opencode and self-serve configuration
  - **no** ``opencode.json`` (never overwrite the project config) and **no**
    ``config.example.toml`` (do not pollute the project root)

Design rules:
- Idempotent: existing destination files are NOT overwritten unless --force.
- --dry-run only prints the plan; never writes.
- Never touches files outside the target (each copy is package-data → target).
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path

# Packaged templates root (regime_driver/data). Works in wheel + source tree.
DATA_DIR = Path(__file__).resolve().parent / "data"

# Deployment manifest: tracks exactly what scaffold wrote, so a user can
# uninstall regime's files precisely WITHOUT touching their own opencode config.
MANIFEST_NAME = ".regime-deployed.json"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass(frozen=True)
class CopyItem:
    src: Path
    dest: Path

    def to_dict(self) -> dict:
        return {"src": str(self.src), "dest": str(self.dest)}


@dataclass
class ScaffoldResult:
    target: Path
    assistants: bool
    dry_run: bool
    copied: list[CopyItem] = field(default_factory=list)
    skipped: list[CopyItem] = field(default_factory=list)
    plan: list[CopyItem] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "target": str(self.target),
            "assistants": self.assistants,
            "dry_run": self.dry_run,
            "copied": [c.to_dict() for c in self.copied],
            "skipped": [c.to_dict() for c in self.skipped],
            "plan": [c.to_dict() for c in self.plan],
        }


def _copies_from(data_subdir: str, target_subdir: str, target: Path) -> list[CopyItem]:
    """Map every file under packaged data/<data_subdir> to target/<target_subdir>."""
    src_root = DATA_DIR / data_subdir
    if not src_root.is_dir():
        return []
    items = []
    for src in sorted(src_root.rglob("*")):
        if not src.is_file():
            continue
        rel = src.relative_to(src_root)
        items.append(CopyItem(src, target / target_subdir / rel))
    return items


def scaffold_plan(target: str | Path, *, assistants: bool = False,
                  workspace: bool = False) -> list[CopyItem]:
    """Compute the full copy plan (read-only; nothing is written).

    ``target`` may be a ``str`` or a ``Path``; it is coerced to ``Path`` so a
    caller cannot trip over ``str``/``Path`` path arithmetic.

    Two deployment modes:

    - **global** (``workspace=False``, default): deploy into a global opencode
      config root (e.g. ``~/.config/opencode``). ``agents/`` (plural — the
      global opencode convention), ``skills/``, ``plugins/``, ``package.json``,
      plus the opencode.json provider template and ``config.example.toml``.
      Affects every opencode session on the machine — **not recommended** for
      most users (it pollutes unrelated conversations).

    - **workspace** (``workspace=True``): deploy into a project-local
      ``<dir>/.opencode/`` directory so only that workspace's opencode sessions
      are affected. The agent directory is ``agent/`` (singular — the project
      opencode convention); skills go to ``skills/`` (``.opencode/skills/`` is
      the project-local skills path opencode discovers); the agent handbook is
      deployed too so the user can read it *inside* opencode and self-serve
      workspace configuration. **No** ``opencode.json`` (never overwrite the
      project config) and **no** ``config.example.toml`` (do not pollute the
      project root).
    """
    target = Path(target)
    plan: list[CopyItem] = []
    agent_dir = "agent" if workspace else "agents"
    plan += _copies_from("agents", agent_dir, target)
    plan += _copies_from("skills", "skills", target)
    if assistants:
        plan += _copies_from("dialog-control-assistants", agent_dir, target)

    # A-route dialog-control carrier (host opencode as the primary dialog):
    #   - the plugin goes to plugins/ (opencode auto-loads local plugins there)
    #   - the dialog-control agent merges into <agent_dir>/ (opencode
    #     auto-discovers markdown agents from both `agent/` and `agents/`)
    #   - a package.json declares the plugin SDK dependency (opencode runs
    #     `bun install` at startup automatically — official plugin mechanism)
    plan += _copies_from("plugins", "plugins", target)
    _dc = DATA_DIR / "dialog-control-agent" / "dialog-control.md"
    if _dc.is_file():
        plan.append(CopyItem(_dc, target / agent_dir / "dialog-control.md"))
    _pkg = DATA_DIR / "opencode-package.json"
    if _pkg.is_file():
        plan.append(CopyItem(_pkg, target / "package.json"))

    if workspace:
        # agent handbook: the machine-oriented operator manual ships with the
        # workspace so the user can ask opencode to read it and self-serve
        # workspace configuration (no global pollution).
        _hb = DATA_DIR / "agent-handbook.md"
        if _hb.is_file():
            plan.append(CopyItem(_hb, target / "agent-handbook.md"))
        # workspace mode never writes opencode.json (project config is the
        # user's own) and never drops config.example.toml into the project.
        return _dedupe(plan)

    # opencode main config (model providers; `{env:...}` placeholders, no secrets).
    # Needed by HOST mode (no docker): without it opencode has no provider entry.
    # Local plugins auto-load; no `plugin` array entry required (official mode).
    _oc = DATA_DIR / "opencode-template" / "opencode.json"
    if _oc.is_file():
        plan.append(CopyItem(_oc, target / "opencode.json"))

    # config.example.toml — the configuration single source of truth. Ship it to
    # <target>/config.example.toml so a wheel user has the reference without
    # cloning the repo (docs/reference/02_configuration.md declares it the truth).
    _cfg = DATA_DIR / "config.example.toml"
    if _cfg.is_file():
        plan.append(CopyItem(_cfg, target / "config.example.toml"))

    # Dedupe by destination (reviewer.md ships in both data/agents and
    # data/dialog-control-assistants; first occurrence wins, content is identical).
    return _dedupe(plan)


def _dedupe(plan: list[CopyItem]) -> list[CopyItem]:
    """Dedupe a copy plan by destination (first occurrence wins)."""
    seen: set[str] = set()
    unique: list[CopyItem] = []
    for item in plan:
        key = str(item.dest)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def scaffold(
    target: str | Path,
    *,
    assistants: bool = False,
    dry_run: bool = False,
    force: bool = False,
    workspace: bool = False,
) -> ScaffoldResult:
    """Deploy the packaged templates to ``target``.

    Args:
        target: destination config root — for global mode e.g. ~/.config/opencode;
            for workspace mode the project-local `.opencode` directory itself
            (the CLI composes `<dir>/.opencode` before calling).
        assistants: also deploy the dialog-control-assistant subagents (analyst/advisor/reviewer).
        dry_run: compute + report the plan without writing anything.
        force: overwrite existing destination files (default: keep them).
        workspace: project-local mode (agent/ singular dir, agent handbook
            shipped, no opencode.json / config.example.toml).

    Returns:
        A ScaffoldResult describing what was copied / skipped.
    """
    target = Path(target)
    result = ScaffoldResult(target=target, assistants=assistants, dry_run=dry_run)
    plan = scaffold_plan(target, assistants=assistants, workspace=workspace)
    result.plan = plan

    for item in plan:
        if item.dest.exists() and not force:
            result.skipped.append(item)
            continue
        if dry_run:
            continue
        item.dest.parent.mkdir(parents=True, exist_ok=True)
        # file copy (not symlink) so the target is fully self-contained
        shutil.copy2(item.src, item.dest)
        result.copied.append(item)

    if not dry_run:
        _write_manifest(target, result.plan, result.copied)
    return result


def _write_manifest(target: Path, plan: list[CopyItem],
                    copied: list[CopyItem] | None = None) -> None:
    """Record exactly which files scaffold owns (for uninstall/recovery).

    The manifest lives at <target>/.regime-deployed.json and records each
    deployed file's path + content hash. ``regime uninstall`` uses it to remove
    ONLY regime's files (preserving anything the user created/changed), and
    ``regime doctor`` uses it to detect drift (deleted / modified / missing).

    It covers the WHOLE plan (not just files freshly copied this run), so an
    idempotent re-run over existing files still records them as regime-owned.
    """
    try:
        from importlib.metadata import version
        _ver = version("regime-driver")
    except Exception:
        _ver = "unknown"
    entries = []
    for item in plan:
        if not item.dest.is_file():
            continue
        entries.append({
            "path": str(item.dest),
            "sha256": _sha256(item.dest),
        })
    manifest = {
        "schema": 1,
        "regime_version": _ver,
        "deployed_at": __import__("time").time(),
        "target": str(target),
        "files": entries,
    }
    (target / MANIFEST_NAME).write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_manifest(target: str | Path) -> dict | None:
    """Read the deployment manifest for a config root, else None."""
    target = Path(target)
    p = target / MANIFEST_NAME
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _contained_in(path: Path, target: Path) -> bool:
    """True when ``path`` is inside ``target`` (defense against a tampered
    manifest pointing at files outside the deployment root)."""
    try:
        path.resolve().relative_to(target.resolve())
        return True
    except ValueError:
        return False


def uninstall(target: str | Path, *, dry_run: bool = False) -> dict:
    """Remove ONLY regime-deployed files from ``target`` (safe uninstall).

    Reads the manifest; for each recorded file:
      - exists + content matches the recorded hash → delete (regime's file)
      - exists + content differs → KEEP (user modified it) and warn
      - missing → already gone (no-op)
      - outside the deployment target (tampered manifest) → SKIP and warn
    Empty parent directories regime created are pruned. The manifest itself is
    removed last. Returns a summary {removed, kept_modified, missing, manifest}.
    """
    target = Path(target)
    manifest = load_manifest(target)
    if manifest is None:
        return {"removed": [], "kept_modified": [], "missing": [],
                "manifest": False, "note": "no deployment manifest found"}

    removed: list[str] = []
    kept_modified: list[str] = []
    missing: list[str] = []
    for entry in manifest.get("files", []):
        p = Path(entry["path"])
        if not _contained_in(p, target):
            kept_modified.append(str(p))   # tampered manifest — never touch outside
            continue
        if not p.is_file():
            missing.append(str(p))
            continue
        if _sha256(p) != entry.get("sha256"):
            kept_modified.append(str(p))   # user changed it — do not delete
            continue
        if not dry_run:
            try:
                p.unlink()
            except OSError:
                kept_modified.append(str(p))
                continue
        removed.append(str(p))

    # prune empty parent dirs we created (walk up, stop at target)
    if not dry_run:
        for p in [Path(x) for x in removed]:
            d = p.parent
            while d != target and d.is_dir() and not any(d.iterdir()):
                d.rmdir()
                d = d.parent

    if not dry_run:
        (target / MANIFEST_NAME).unlink(missing_ok=True)
    return {"removed": removed, "kept_modified": kept_modified,
            "missing": missing, "manifest": True,
            "dry_run": dry_run}


def check_deployed(target: str | Path) -> dict:
    """Verify manifest ↔ disk consistency (drift detection for doctor).

    Returns {deployed, ok, missing, modified, extra_manifest, detail}.
    """
    target = Path(target)
    manifest = load_manifest(target)
    if manifest is None:
        return {"deployed": False, "ok": True, "detail": "not deployed"}
    missing: list[str] = []
    modified: list[str] = []
    for entry in manifest.get("files", []):
        p = Path(entry["path"])
        if not _contained_in(p, target):
            modified.append(str(p))   # tampered manifest — flag, never delete
        elif not p.is_file():
            missing.append(str(p))
        elif _sha256(p) != entry.get("sha256"):
            modified.append(str(p))
    ok = not missing and not modified
    return {"deployed": True, "ok": ok, "missing": missing,
            "modified": modified,
            "detail": f"{len(manifest.get('files', []))} files tracked"}


def templates_ready() -> dict:
    """Doctor-style check: are the packaged templates present and non-empty?"""
    subdirs = {
        "skills": ["design-philosophy", "code-review", "developer-quality"],
        "agents": ["reviewer.md"],
        "dialog-control-assistants": ["analyst.md", "advisor.md"],
    }
    checks: list[dict] = []
    for subdir, expected in subdirs.items():
        root = DATA_DIR / subdir
        if not root.is_dir():
            checks.append({"template": subdir, "ok": False, "detail": "missing dir"})
            continue
        missing = [e for e in expected if not (root / e).exists()]
        if missing:
            checks.append({"template": subdir, "ok": False,
                           "detail": f"missing: {missing}"})
        else:
            checks.append({"template": subdir, "ok": True, "detail": f"{len(expected)} expected files"})
    return {"ok": all(c["ok"] for c in checks), "checks": checks}


def check_plugin(plugins_dir: str | Path | None = None) -> dict:
    """Doctor-style check: is the A-route dialog-control plugin deployed in a
    shape opencode's auto-scan loader reliably loads?

    opencode (v1.18.x) auto-scans ``{plugin,plugins}/*.{ts,js}`` under each
    config directory; a file that does NOT default-export the v1 plugin form
    (``{ id, server }``) can be silently skipped. This check verifies the
    deployed file exists and carries that shape, so a user learns before
    starting opencode whether the dialog-control plugin will actually load.

    Args:
        plugins_dir: the plugins directory to inspect (default: the packaged
            data/plugins, i.e. what ``regime scaffold`` would deploy). A real
            deployment can be checked by passing e.g.
            ``~/.config/opencode/plugins`` or ``<ws>/.opencode/plugins``.

    Returns ``{ok, detail, ...}`` (never raises).
    """
    import re

    plugins_dir = Path(plugins_dir) if plugins_dir else DATA_DIR / "plugins"
    plugin = plugins_dir / "regime-dialog-control.js"
    if not plugin.is_file():
        return {"ok": False, "detail": f"plugin not deployed: {plugin}",
                "path": str(plugin)}
    text = plugin.read_text(encoding="utf-8", errors="replace")
    # v1 default-export shape: `export default { id: "...", server: ... }`.
    # Strip line comments first so comment text can never satisfy the shape,
    # then require BOTH keys inside the default-export object (order-independent).
    code = re.sub(r"^\s*//.*$", "", text, flags=re.M)
    m = re.search(r"export\s+default\s*\{", code)
    if m is None:
        return {"ok": False,
                "detail": f"plugin lacks `export default` — opencode may "
                          f"silently skip it: {plugin}",
                "path": str(plugin)}
    obj = code[m.end():]
    has_id = re.search(r"^\s*id\s*:\s*[\"'][^\"']+[\"']\s*,?", obj, re.M) is not None
    has_server = re.search(r"^\s*server\s*:", obj, re.M) is not None
    if not (has_id and has_server):
        return {"ok": False,
                "detail": f"plugin default export must carry both `id` and "
                          f"`server` (found id={has_id} server={has_server}) — "
                          f"opencode may silently skip it: {plugin}",
                "path": str(plugin)}
    return {"ok": True,
            "detail": f"plugin loadable shape OK: {plugin}",
            "path": str(plugin)}


def precheck_workspace(workspace: str | Path, *, config_root: str | Path | None = None) -> dict:
    """Pre-install inspection of a project dir before workspace-mode deploy.

    Answers the user-facing questions that decide whether workspace install is
    safe and what the helper should tell the user:

    - Does ``<dir>/.opencode`` already exist? (opencode may have created it, or
      a previous regime install may be present.)
    - Does it contain files the USER owns (their own plugins/agents/skills, or
      a previous regime deployment)? regime never overwrites existing files
      unless ``--force``, but a name collision (e.g. the user already has a
      ``plugins/regime-dialog-control.js``) would silently keep the user's file
      and break the A-route plugin — the user should tidy the workspace first.
    - Is ``<dir>`` inside a git repo, and is ``.opencode`` ignored? (advise
      ``.gitignore`` so the deployed files are not committed by accident.)
    - Is an opencode process running? (advise restart after install so the new
      plugin/agent/skills are loaded.)

    Pure inspection — never writes, never mutates. Returns
    ``{ok, opencode_dir, exists, regime_owned, user_files, collisions, is_git,
    gitignored, opencode_running, notes}`` where ``ok`` is False only when a
    blocking collision exists (a user file at a path regime would write).
    """
    workspace = Path(workspace)
    oc_dir = workspace / ".opencode"
    manifest = load_manifest(oc_dir)

    # files inside .opencode that regime does NOT own (no manifest, or not in it)
    regime_paths: set[str] = set()
    if manifest:
        regime_paths = {str(Path(e["path"]).resolve()) for e in manifest.get("files", [])}
    user_files: list[str] = []
    collisions: list[str] = []
    if oc_dir.is_dir():
        for p in sorted(oc_dir.rglob("*")):
            if not p.is_file() or p.name == MANIFEST_NAME:
                continue
            rel = str(p.relative_to(oc_dir))
            if str(p.resolve()) in regime_paths:
                continue
            user_files.append(rel)
            # a user file at exactly a path regime would write = collision
            if p.name == "regime-dialog-control.js" and p.parent.name == "plugins":
                collisions.append(rel)
            elif p.name == "dialog-control.md" and p.parent.name in ("agent", "agents"):
                collisions.append(rel)
            elif p.name == "package.json":
                collisions.append(rel)

    # git repo + .gitignore advice
    is_git = False
    gitignored = False
    d = workspace
    while d != d.parent:
        if (d / ".git").is_dir():
            is_git = True
            break
        d = d.parent
    if is_git:
        gi = workspace / ".gitignore"
        gitignored = gi.is_file() and ".opencode" in gi.read_text(encoding="utf-8", errors="replace")

    # opencode process detection (best-effort; POSIX only). Match the opencode
    # binary itself (exact process name) or its serve/tui invocations — NOT any
    # process whose command line merely contains "opencode" in a path (e.g.
    # `regime events --ledger /tmp/opencode/...` would be a false positive).
    opencode_running = False
    try:
        import shutil
        import subprocess
        if shutil.which("pgrep"):
            proc = subprocess.run(
                ["pgrep", "-x", "opencode"], capture_output=True, text=True,
                timeout=5)
            opencode_running = proc.returncode == 0 and bool(proc.stdout.strip())
    except Exception:
        opencode_running = False

    notes: list[str] = []
    if oc_dir.is_dir() and manifest:
        notes.append("已检测到 regime 先前部署（manifest 存在）——重跑幂等，`--force` 可覆盖")
    if not oc_dir.is_dir():
        notes.append("`.opencode/` 尚不存在——regime 将创建它；opencode 下次启动自动扫描加载")
    if oc_dir.is_dir() and not manifest and not user_files:
        notes.append("`.opencode/` 已存在但为空（opencode 可能已初始化）——regime 部署不会与其冲突")
    if user_files and not collisions:
        notes.append(f"`.opencode/` 含 {len(user_files)} 个非 regime 文件（你的自有配置）——"
                     "regime 不会覆盖它们；但建议先整理工作区，避免混淆")
    if collisions:
        notes.append("⚠ 检测到路径冲突：你已有同名文件，regime 将保留你的文件（不覆盖）——"
                     "但 A 路插件/对话框 agent 可能不会按预期加载。建议先整理工作区（移走或改名冲突文件）再装")
    if is_git and not gitignored:
        notes.append("目录在 git 仓库内且 `.opencode` 未忽略——建议在 `.gitignore` 加一行 `.opencode/`")
    if opencode_running:
        notes.append("检测到 opencode 正在运行——装完后需要重启 opencode 才能加载新插件/agent/skills")

    return {
        "ok": not collisions,
        "opencode_dir": str(oc_dir),
        "exists": oc_dir.is_dir(),
        "regime_owned": manifest is not None,
        "user_files": user_files,
        "collisions": collisions,
        "is_git": is_git,
        "gitignored": gitignored,
        "opencode_running": opencode_running,
        "notes": notes,
    }
