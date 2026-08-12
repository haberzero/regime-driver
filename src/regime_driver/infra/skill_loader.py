"""Skill loading for reviewer injection (infra: file I/O).

Reads a skill's SKILL.md from the workflow-regime skills directory, strips the
YAML frontmatter, and returns the body text for injection into the reviewer
prompt. Skills are never preset into any session; they are injected per node
by the robot at the moment of a reviewer call.
"""

from __future__ import annotations

import re
from pathlib import Path

# Default skills root: the packaged templates inside this package (works in a
# wheel install and in the source tree alike). No source-tree assumption.
DEFAULT_SKILLS_DIR = Path(__file__).resolve().parent.parent / "data" / "skills"

_FRONTMATTER_RE = re.compile(r"^---\s*\n.*?\n---\s*\n?", re.DOTALL)


class SkillNotFoundError(Exception):
    """Raised when a requested skill does not exist."""


def _resolve_skill_path(skill_name: str, skills_dir: str | Path | None) -> Path:
    """Resolve a skill to its SKILL.md, guarding against path traversal.

    skill_name must be a single path component (no separators/..) so a crafted
    name cannot escape the skills root.
    """
    if not skill_name or "/" in skill_name or "\\" in skill_name or skill_name in (".", ".."):
        raise SkillNotFoundError(f"invalid skill name: {skill_name!r}")
    root = Path(skills_dir) if skills_dir else DEFAULT_SKILLS_DIR
    return root / skill_name / "SKILL.md"


def load_skill(skill_name: str, skills_dir: str | Path | None = None) -> str:
    """Return the body of a skill's SKILL.md (frontmatter stripped).

    Args:
        skill_name: skill directory name (e.g. "design-philosophy").
        skills_dir: override the skills root directory.

    Returns:
        The skill markdown body text.
    """
    path = _resolve_skill_path(skill_name, skills_dir)
    if not path.exists():
        raise SkillNotFoundError(f"skill '{skill_name}' not found at {path}")
    raw = path.read_text(encoding="utf-8")
    return _FRONTMATTER_RE.sub("", raw, count=1).strip()