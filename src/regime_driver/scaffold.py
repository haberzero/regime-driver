"""regime scaffold: one-shot deployment of the packaged official templates.

The distributed wheel ships the templates under ``regime_driver/data/`` (skills,
agents, dialog-control-assistant subagents, docker recipes, regime.json). ``scaffold`` copies
them to an opencode config target (default ``~/.config/opencode``) so a fresh
user does not need to clone the source repository:

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


def scaffold_plan(target: str | Path, *, assistants: bool = False) -> list[CopyItem]:
    """Compute the full copy plan (read-only; nothing is written).

    ``target`` may be a ``str`` or a ``Path``; it is coerced to ``Path`` so a
    caller cannot trip over ``str``/``Path`` path arithmetic.
    """
    target = Path(target)
    plan: list[CopyItem] = []
    plan += _copies_from("agents", "agents", target)
    plan += _copies_from("skills", "skills", target)
    if assistants:
        plan += _copies_from("dialog-control-assistants", "agents", target)

    # A-route dialog-control carrier (host opencode as the primary dialog):
    #   - the plugin goes to plugins/ (opencode auto-loads local plugins there)
    #   - the dialog-control agent merges into agents/ (opencode auto-discovers
    #     markdown agents there)
    #   - a package.json declares the plugin SDK dependency (opencode runs
    #     `bun install` at startup automatically — official plugin mechanism)
    plan += _copies_from("plugins", "plugins", target)
    _dc = DATA_DIR / "dialog-control-agent" / "dialog-control.md"
    if _dc.is_file():
        plan.append(CopyItem(_dc, target / "agents" / "dialog-control.md"))
    _pkg = DATA_DIR / "opencode-package.json"
    if _pkg.is_file():
        plan.append(CopyItem(_pkg, target / "package.json"))

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
) -> ScaffoldResult:
    """Deploy the packaged templates to ``target``.

    Args:
        target: destination config root (e.g. ~/.config/opencode); str or Path.
        assistants: also deploy the dialog-control-assistant subagents (analyst/advisor/reviewer).
        dry_run: compute + report the plan without writing anything.
        force: overwrite existing destination files (default: keep them).

    Returns:
        A ScaffoldResult describing what was copied / skipped.
    """
    target = Path(target)
    result = ScaffoldResult(target=target, assistants=assistants, dry_run=dry_run)
    plan = scaffold_plan(target, assistants=assistants)
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


def uninstall(target: str | Path, *, dry_run: bool = False) -> dict:
    """Remove ONLY regime-deployed files from ``target`` (safe uninstall).

    Reads the manifest; for each recorded file:
      - exists + content matches the recorded hash → delete (regime's file)
      - exists + content differs → KEEP (user modified it) and warn
      - missing → already gone (no-op)
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
        if not p.is_file():
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
