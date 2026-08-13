"""Capability-map consistency guard (WORK_PLAN8 stage-4).

Ensures `docs/capabilities.md` stays the single source of truth for the
capability map: every CLI command referenced exists, every skill mounted on a
default-flow node is packaged, and quality-task covers tags are well-formed.
"""

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "ops" / "check_capabilities.py"


def _run_check() -> dict:
    p = subprocess.run(
        [sys.executable, str(SCRIPT), "--json"], capture_output=True, text=True)
    assert p.returncode == 0, f"check_capabilities failed:\n{p.stdout}\n{p.stderr}"
    return json.loads(p.stdout)


def test_capability_map_in_sync_with_implementation():
    report = _run_check()
    assert report["ok"] is True
    assert report["cli_subcommands"] >= 20
    assert "developer-quality" in report["mounted_skills"]
    assert "code-review" in report["mounted_skills"]
    assert "design-philosophy" in report["mounted_skills"]
    # WORK_PLAN9: the suite was redesigned from 8 shallow single-module tasks
    # to 4 complex multi-file tasks; each declares MORE capabilities per task
    # (10 / 10 / 8 / 9), so the total tag count dropped while coverage depth
    # rose. Assert depth-per-task and a meaningful total instead of a raw cap.
    assert report["covers_tags"] >= 15
    # WORK_PLAN9 complex-suite depth markers (see quality_tasks.py):
    for marker in ("multi-module", "design-node", "thread-safety",
                   "read-existing-code"):
        assert marker in report["covers_list"], f"missing covers tag {marker!r}"


def test_every_covers_tag_declared_in_capabilities_section5():
    """No covers tag may be exercised by a task without being declared in the
    capability map's §五 task↔capability table (single source of truth)."""
    import re

    caps = (REPO / "docs" / "capabilities.md").read_text(encoding="utf-8")
    section_five = caps.split("## 五")[1] if "## 五" in caps else ""
    declared: set[str] = set()
    for ln in section_five.splitlines():
        if ln.lstrip().startswith("|") and not ln.lstrip().startswith("|---"):
            declared |= set(re.findall(r"[\w-]+", ln))
    tasks = (REPO / "ops" / "quality_tasks.py").read_text(encoding="utf-8")
    used: set[str] = set()
    for block in re.findall(r"covers=\(([^)]*)\)", tasks, re.S):
        used |= set(re.findall(r"['\"]([\w-]+)['\"]", block))
    assert used, "no covers tags found in quality_tasks.py"
    undeclared = sorted(used - declared)
    assert not undeclared, (
        f"covers tags not declared in capabilities.md §五: {undeclared}")


def test_every_capability_has_verifier():
    """Every capability in capabilities.md §一 must reference a verifier (a
    quality task or an explicit '—'); nothing is documented without a way to
    verify it exists."""
    caps = (REPO / "docs" / "capabilities.md").read_text(encoding="utf-8")
    section_one = caps.split("## 一")[1].split("## 二")[0]
    rows = [ln for ln in section_one.splitlines() if ln.startswith("|")]
    for row in rows[1:]:
        cells = [c.strip() for c in row.strip("|").split("|")]
        assert len(cells) >= 4, f"malformed capability row: {row}"
        # the verifier column is non-empty; '—' is an accepted explicit marker
        assert cells[3], f"capability {cells[0]!r} has no verifier: {row}"
