"""Packaged-template regression tests (WORK_PLAN7 I).

Guards the "对外供给就绪" hard gap: the distributed wheel must carry the
templates that the runtime depends on (skills / agents / god-assistants /
docker recipes / regime.json), and the runtime must resolve them from the
package rather than from a source-tree checkout.

The wheel-build test is intentionally real: it builds the actual wheel via the
same hatchling backend used in CI/release and inspects its contents, so a
forgotten template can never silently disappear from the distribution.
"""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from regime_driver.infra.regime_loader import DEFAULT_REGIME
from regime_driver.infra.skill_loader import DEFAULT_SKILLS_DIR

REPO = Path(__file__).parent.parent
PKG = REPO / "src" / "regime_driver"


# ---------------------------------------------------------------------------
# packaged data presence (source tree mirrors the wheel: hatchling includes
# everything under the package directory, so the wheel inherits these)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("relative", [
    "data/skills/design-philosophy/SKILL.md",
    "data/skills/code-review/SKILL.md",
    "data/agents/reviewer.md",
    "data/god-assistants/analyst.md",
    "data/god-assistants/advisor.md",
    "data/docker/Dockerfile.worker",
    "data/docker/Dockerfile.god",
    "data/docker/worker-config/opencode.json",
    "data/docker/god-config/opencode.json",
])
def test_packaged_template_file_exists(relative: str):
    assert (PKG / relative).is_file(), f"missing packaged template: {relative}"


def test_packaged_templates_complete():
    """Every workflow-regime skill and both agent sets ship inside the package."""
    expected_skills = {p.name for p in (REPO / "workflow-regime" / "skills").iterdir() if p.is_dir()}
    packaged_skills = {p.name for p in (PKG / "data" / "skills").iterdir() if p.is_dir()}
    assert expected_skills <= packaged_skills, expected_skills - packaged_skills

    packaged_agents = {p.name for p in (PKG / "data" / "agents").iterdir()}
    assert "reviewer.md" in packaged_agents, packaged_agents
    god_agents = {p.name for p in (PKG / "data" / "god-assistants").iterdir()}
    assert {"analyst.md", "advisor.md", "reviewer.md"} <= god_agents, god_agents


# ---------------------------------------------------------------------------
# runtime resolution does NOT depend on the source tree
# ---------------------------------------------------------------------------

def test_default_skills_dir_is_packaged_not_source_tree():
    """DEFAULT_SKILLS_DIR must resolve inside the package (data/skills), never
    to a sibling 'workflow-regime' of the repo root."""
    assert DEFAULT_SKILLS_DIR.resolve() == (PKG / "data" / "skills").resolve()
    assert DEFAULT_SKILLS_DIR.is_dir()
    assert "workflow-regime" not in str(DEFAULT_SKILLS_DIR)


def test_default_regime_is_packaged():
    assert DEFAULT_REGIME.resolve() == (PKG / "data" / "regime.json").resolve()
    assert DEFAULT_REGIME.is_file()


def test_packaged_example_flow_preflights_clean():
    """The shipped example flow must stay valid AND preflight COMPLETE, or it is
    a broken example (external readers load it to learn tool/route branching)."""
    from regime_driver.app.preflight import preflight
    from regime_driver.infra.regime_loader import load_regime

    example = PKG / "data" / "examples" / "verify_then_report.json"
    assert example.is_file()
    sm = load_regime(example)
    res = preflight(sm)
    assert res["ok"] is True, f"example preflight failed: {res}"


def test_packaged_templates_match_true_sources():
    """Single-source-of-truth guard (WORK_PLAN7 III): the packaged data/ copies
    must stay byte-identical to their true sources, so no drift is possible."""
    pairs = [
        ("data/agents", "docker/worker-config/agents"),
        ("data/god-assistants", "docker/god-config/agents"),
        ("data/skills", "workflow-regime/skills"),
        ("data/docker", "docker"),
    ]
    for pkg_rel, src_rel in pairs:
        pkg_dir = PKG / pkg_rel
        src_dir = REPO / src_rel
        assert pkg_dir.is_dir(), f"packaged dir missing: {pkg_rel}"
        assert src_dir.is_dir(), f"true source missing: {src_rel}"
        assert _dirs_equal(pkg_dir, src_dir), (
            f"drift between {pkg_rel} and {src_rel}: {_dir_diff(pkg_dir, src_dir)}"
        )

    # reviewer.md ships in BOTH data/agents and data/god-assistants (both map
    # to the same target agents/reviewer.md). If their true sources ever
    # diverge, scaffold's dedupe silently drops one — so require them equal.
    import filecmp
    assert filecmp.cmp(
        REPO / "docker" / "worker-config" / "agents" / "reviewer.md",
        REPO / "docker" / "god-config" / "agents" / "reviewer.md",
        shallow=False,
    )


def _dirs_equal(a: Path, b: Path) -> bool:
    import filecmp
    fa = {p.relative_to(a) for p in a.rglob("*") if p.is_file()}
    fb = {p.relative_to(b) for p in b.rglob("*") if p.is_file()}
    if fa != fb:
        return False
    return all(filecmp.cmp(a / rel, b / rel, shallow=False) for rel in fa)


def _dir_diff(a: Path, b: Path) -> str:
    import filecmp
    fa = {p.relative_to(a) for p in a.rglob("*") if p.is_file()}
    fb = {p.relative_to(b) for p in b.rglob("*") if p.is_file()}
    only_a = fa - fb
    only_b = fb - fa
    changed = [str(r) for r in (fa & fb) if not filecmp.cmp(a / r, b / r, shallow=False)]
    return f"only in pkg: {only_a}; only in src: {only_b}; changed: {changed}"


# ---------------------------------------------------------------------------
# real wheel build: the distribution itself carries the templates, and a
# source-tree-free process resolves them correctly
# ---------------------------------------------------------------------------

def _build_wheel(tmp_path: Path) -> Path:
    out = tmp_path / "dist"
    out.mkdir()
    subprocess.run(
        [sys.executable, "-m", "pip", "wheel", ".", "--no-deps",
         "--no-build-isolation", "-q", "-w", str(out)],
        cwd=REPO, check=True, capture_output=True, text=True,
    )
    wheels = list(out.glob("*.whl"))
    assert len(wheels) == 1, wheels
    return wheels[0]


def _wheel_entries(wheel: Path) -> set[str]:
    with zipfile.ZipFile(wheel) as zf:
        return set(zf.namelist())


def test_wheel_contains_templates(tmp_path):
    wheel = _build_wheel(tmp_path)
    entries = _wheel_entries(wheel)

    for entry in [
        "regime_driver/data/skills/design-philosophy/SKILL.md",
        "regime_driver/data/skills/code-review/SKILL.md",
        "regime_driver/data/agents/reviewer.md",
        "regime_driver/data/god-assistants/analyst.md",
        "regime_driver/data/god-assistants/advisor.md",
        "regime_driver/data/docker/Dockerfile.worker",
        "regime_driver/data/docker/Dockerfile.god",
        "regime_driver/data/regime.json",
        "regime_driver/data/examples/verify_then_report.json",
    ]:
        assert entry in entries, f"wheel missing packaged template: {entry}"

    # A skill dir must be exactly regime_driver/data/skills/<name>/SKILL.md; any
    # other depth (a stray file directly under data/skills/, or a nested
    # subdirectory) is a packaging anomaly worth failing on.
    prefix = "regime_driver/data/skills/"
    skill_dirs = set()
    for e in entries:
        if not e.startswith(prefix) or e.endswith("/"):
            continue  # skip directory entries
        rel = e[len(prefix):]
        parts = rel.split("/")
        if len(parts) != 2 or parts[1] != "SKILL.md":
            raise AssertionError(f"unexpected wheel skill entry shape: {e!r}")
        skill_dirs.add(parts[0])
    expected = {p.name for p in (REPO / "workflow-regime" / "skills").iterdir() if p.is_dir()}
    assert expected <= skill_dirs, expected - skill_dirs


def test_wheel_preflight_without_source_tree(tmp_path):
    """Install the wheel to an isolated dir, run preflight in a subprocess whose
    cwd/sys.path never touch the repo source tree, and require COMPLETE.

    This is the decisive acceptance test for the audit's hard gap: before the
    fix, a source-tree-free user's preflight died on 'skill not found'."""
    wheel = _build_wheel(tmp_path)
    install = tmp_path / "site"
    install.mkdir()
    subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-deps", "--no-build-isolation",
         "--target", str(install), str(wheel)],
        check=True, capture_output=True, text=True,
    )

    # Run from /tmp with PYTHONPATH=install so the repo source tree is invisible.
    code = (
        "from regime_driver.app.preflight import preflight; "
        "from regime_driver.infra.skill_loader import DEFAULT_SKILLS_DIR; "
        "import regime_driver; "
        "assert 'workflow-regime' not in str(DEFAULT_SKILLS_DIR), DEFAULT_SKILLS_DIR; "
        "r = preflight(); "
        "print('PKG', regime_driver.__file__); "
        "print('SKILLS', DEFAULT_SKILLS_DIR); "
        "print('RESULT', r['ok'], r['outcome'])"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        cwd=tmp_path, env={"PYTHONPATH": str(install), "PATH": "/usr/bin:/bin"},
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"stderr:\n{proc.stderr}"
    assert "RESULT True complete" in proc.stdout
    assert "workflow-regime" not in proc.stdout
