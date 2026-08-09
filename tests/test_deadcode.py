"""Dead-code guard: fail if a production API has no non-test consumer.

Prevents the recurring "half-wired feature" debt (A1-A3 / G9/G14): an API that
only tests call is dead capability. Any public method of the core client /
reporter / permission modules must be referenced somewhere in the runtime
package (excluding its own definition and the testing/ doubles).
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "regime_driver"
# modules whose public methods we guard; value = expected callers (optional)
GUARDED = {
    "infra/opencode.py": {},
    "supervisor.py": {},
    "task.py": {},
    "drive.py": {},
    "worker.py": {},
    "fleet.py": {},
    "app/reporter.py": {},
    "app/preflight.py": {},
    "app/god_dialog.py": {},
}


def _collect_methods(path: Path) -> set[str]:
    text = path.read_text(encoding="utf-8")
    # only public methods (not underscore-prefixed); private helpers are internal
    return {m for m in re.findall(r"^    def (\w+)\(", text, re.M) if not m.startswith("_")}


def _package_texts() -> dict[str, str]:
    out = {}
    for p in (SRC / "app", SRC / "core", SRC / "infra", SRC / "cli"):
        for f in p.glob("*.py"):
            out[str(f.relative_to(SRC))] = f.read_text(encoding="utf-8")
    for f in SRC.glob("*.py"):  # top-level package modules (supervisor.py etc.)
        out[f.name] = f.read_text(encoding="utf-8")
    return out


def test_no_dead_public_methods() -> None:
    """Every public method of a guarded module must be called somewhere.

    A call anywhere in the package (including same-file internal calls, but not
    the `def` itself) counts as a consumer. Catches truly-dead public API that
    only tests reference.
    """
    texts = _package_texts()
    for rel, _ in GUARDED.items():
        path = SRC / rel
        if not path.exists():
            continue
        for method in _collect_methods(path):
            # find any `.method(` call across the package (any file incl. own)
            caller = next(
                (other for other, body in texts.items()
                 if re.search(rf"(?<!def )\.{method}\(", body)),
                None,
            )
            assert caller is not None, (
                f"dead public method: {rel}::{method} has no production consumer "
                f"(only tests use it). Wire it or remove it."
            )
