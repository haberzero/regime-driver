#!/usr/bin/env python3
"""Sync packaged templates from their true sources into src/regime_driver/data/.

Single-source-of-truth (WORK_PLAN7 III): the official agent/skill templates live
in ONE place per asset class —
    agents   → docker/worker-config/agents/   (developer/reviewer)
    dialog-control → docker/dialog-control-config/agents/  (analyst/advisor/reviewer)
    skills   → workflow-regime/skills/        (runtime skills)
    docker   → docker/                        (worker/dialog-control recipes)
    config.example.toml → data/config.example.toml  (config reference, single truth)
and the packaged copies under src/regime_driver/data/ are DERIVED — they ship in
the wheel so a pip user gets the templates without cloning the repo.

Run after editing any true source. `tests/test_package.py` has a drift guard
(test_packaged_templates_match_true_sources) that fails CI if they diverge.

Usage:
    python ops/sync_templates.py        # copy true sources -> data/
    python ops/sync_templates.py --check  # verify they match (exit 1 on drift)
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "src" / "regime_driver" / "data"

# (packaged subdir, true source dir)
PAIRS = [
    ("agents", REPO / "docker" / "worker-config" / "agents"),
    ("dialog-control-assistants", REPO / "docker" / "dialog-control-config" / "agents"),
    ("skills", REPO / "workflow-regime" / "skills"),
    ("docker", REPO / "docker"),
]

# single-file syncs: (packaged name, true source file)
FILES = [
    ("config.example.toml", REPO / "config.example.toml"),
]


def _dirs_equal(a: Path, b: Path) -> bool:
    fa = {p.relative_to(a) for p in a.rglob("*") if p.is_file()}
    fb = {p.relative_to(b) for p in b.rglob("*") if p.is_file()}
    if fa != fb:
        return False
    return all(filecmp.cmp(a / rel, b / rel, shallow=False) for rel in fa)


def sync() -> None:
    for sub, src in PAIRS:
        dst = DATA / sub
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(src, dst)
        print(f"synced {sub} <- {src.relative_to(REPO)}")
    for name, src in FILES:
        dst = DATA / name
        shutil.copy2(src, dst)
        print(f"synced {name} <- {src.relative_to(REPO)}")


def check() -> bool:
    ok = True
    for sub, src in PAIRS:
        dst = DATA / sub
        if not dst.is_dir() or not _dirs_equal(dst, src):
            print(f"[DRIFT] {sub}: packaged {dst} != true source {src}", file=sys.stderr)
            ok = False
    for name, src in FILES:
        dst = DATA / name
        if not dst.is_file() or not filecmp.cmp(dst, src, shallow=False):
            print(f"[DRIFT] {name}: packaged {dst} != true source {src}", file=sys.stderr)
            ok = False
    if ok:
        print("packaged templates in sync with true sources")
    return ok


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="verify sync; no writes")
    args = ap.parse_args()
    if args.check:
        sys.exit(0 if check() else 1)
    sync()


if __name__ == "__main__":
    main()
