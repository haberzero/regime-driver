"""CLI-contract drift guard (WORK_PLAN11+).

Prevents the exact breakage the 2026-08-13 audit found: the reference doc listed
`run-many --workers` (a `drive-many`-only option) and `run --preflight` (a
non-existent option) — an agent following the doc would get a typer "No such
option" error.

Guard: every `--param` referenced in `docs/reference/01_cli.md` must exist in
the CLI source (so a doc-only phantom option is a test failure).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CLI = REPO / "src" / "regime_driver" / "cli" / "__init__.py"
DOC = REPO / "docs" / "reference" / "01_cli.md"


def _real_params() -> set[str]:
    """All --param names declared anywhere in the CLI source (all sub-apps)."""
    real: set[str] = set()
    for path in [CLI] + sorted((REPO / "src" / "regime_driver").rglob("*.py")):
        if "cli" not in str(path):
            continue
        real |= set(re.findall(r"--([a-z][a-z0-9-]*)", path.read_text(encoding="utf-8")))
    return {p for p in real if p}


def test_doc_params_exist_in_cli():
    doc = set(re.findall(r"--([a-z][a-z0-9-]*)", DOC.read_text(encoding="utf-8")))
    real = _real_params()
    phantom = sorted(doc - real)
    assert not phantom, (
        f"01_cli.md references CLI options that do not exist: {phantom}\n"
        "A doc-only option makes the dialog control agent fail with typer "
        "'No such option'. Fix the doc (or implement the option).")


def test_run_and_run_many_params_match_help():
    """The run / run-many doc tables must not list options those commands lack
    (the audit's two blockers: run-many --workers, run --preflight)."""
    # reflect the actual run / run-many signatures from the source
    src = CLI.read_text(encoding="utf-8")
    for cmd in ("run", "run_many"):
        m = re.search(rf"def {cmd}\(.*?\)\s*->", src, re.S)
        assert m, f"could not find def {cmd}"
        body = m.group(0)
        params = set(re.findall(r'"--([a-z][a-z0-9-]*)"', body))
        # doc table for this command: section between '### `X`' and the next '###'
        cmd_doc = f"### `{cmd.replace('_', '-')}`"
        full = DOC.read_text(encoding="utf-8")
        start = full.index(cmd_doc)
        rest = full[start:]
        end = rest.find("\n### ", 1)
        section = rest[:end] if end > 0 else rest
        # only leading-column table rows (`| `--param` ...`) are option listings
        doc_params = set(re.findall(r"^\|\s*`--([a-z][a-z0-9-]*)`", section, re.M))
        phantom = doc_params - params
        assert not phantom, (
            f"01_cli.md `{cmd}` table lists options the command lacks: {sorted(phantom)}")
