"""God Dialog REPL demo — one dialog that controls & monitors workflows.

Thin wrapper over the shared `regime_driver.app.dialog_app.run_dialog`, so the
dialog logic lives in one place (see `regime dialog` CLI). Uses MockClient by
default (offline, no LLM); pass --live to use the real worker.

Usage:
  python ops/god_dialog.py                  # offline (MockClient, no LLM)
  python ops/god_dialog.py --live           # real worker (deepseek-api)
  python ops/god_dialog.py --help
"""
from __future__ import annotations

import argparse
import sys

sys.path.insert(0, "/home/haber/oc-meta/src")

from regime_driver.app.dialog_app import run_dialog


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--live", action="store_true", help="use the real worker")
    ap.add_argument("--base", default="http://127.0.0.1:4097")
    ap.add_argument("--model", default="deepseek-api/deepseek-v4-flash")
    ap.add_argument("--timeout", type=float, default=240.0)
    a = ap.parse_args()
    return run_dialog(a.base, a.model, live=a.live, timeout=a.timeout)


if __name__ == "__main__":
    sys.exit(main())