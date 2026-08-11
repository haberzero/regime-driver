"""regime scaffold: one-shot deployment of the packaged official templates.

The distributed wheel ships the templates under ``regime_driver/data/`` (skills,
agents, god-assistant subagents, docker recipes, regime.json). ``scaffold`` copies
them to an opencode config target (default ``~/.config/opencode``) so a fresh
user does not need to clone the source repository:

- agents   → <target>/agents/       (developer/reviewer templates)
- skills   → <target>/skills/       (the runtime skills the flows reference)
- --god    → also copies the god-assistant subagents (analyst/advisor/reviewer)
           → <target>/agents/

Design rules:
- Idempotent: existing destination files are NOT overwritten unless --force.
- --dry-run only prints the plan; never writes.
- Never touches files outside the target (each copy is package-data → target).
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass, field
from pathlib import Path

# Packaged templates root (regime_driver/data). Works in wheel + source tree.
DATA_DIR = Path(__file__).resolve().parent / "data"


@dataclass(frozen=True)
class CopyItem:
    src: Path
    dest: Path

    def to_dict(self) -> dict:
        return {"src": str(self.src), "dest": str(self.dest)}


@dataclass
class ScaffoldResult:
    target: Path
    god: bool
    dry_run: bool
    copied: list[CopyItem] = field(default_factory=list)
    skipped: list[CopyItem] = field(default_factory=list)
    plan: list[CopyItem] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "target": str(self.target),
            "god": self.god,
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


def scaffold_plan(target: str | Path, *, god: bool = False) -> list[CopyItem]:
    """Compute the full copy plan (read-only; nothing is written).

    ``target`` may be a ``str`` or a ``Path``; it is coerced to ``Path`` so a
    caller cannot trip over ``str``/``Path`` path arithmetic.
    """
    target = Path(target)
    plan: list[CopyItem] = []
    plan += _copies_from("agents", "agents", target)
    plan += _copies_from("skills", "skills", target)
    if god:
        plan += _copies_from("god-assistants", "agents", target)

    # Dedupe by destination (reviewer.md ships in both data/agents and
    # data/god-assistants; first occurrence wins, content is identical).
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
    god: bool = False,
    dry_run: bool = False,
    force: bool = False,
) -> ScaffoldResult:
    """Deploy the packaged templates to ``target``.

    Args:
        target: destination config root (e.g. ~/.config/opencode); str or Path.
        god: also deploy the god-assistant subagents (analyst/advisor/reviewer).
        dry_run: compute + report the plan without writing anything.
        force: overwrite existing destination files (default: keep them).

    Returns:
        A ScaffoldResult describing what was copied / skipped.
    """
    target = Path(target)
    result = ScaffoldResult(target=target, god=god, dry_run=dry_run)
    plan = scaffold_plan(target, god=god)
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
    return result


def templates_ready() -> dict:
    """Doctor-style check: are the packaged templates present and non-empty?"""
    subdirs = {
        "skills": ["design-philosophy", "code-review"],
        "agents": ["reviewer.md"],
        "god-assistants": ["analyst.md", "advisor.md"],
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
