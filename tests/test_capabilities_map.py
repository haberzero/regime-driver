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
    assert report["covers_tags"] >= 20
