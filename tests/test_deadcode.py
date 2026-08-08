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
    "infra/opencode.py": {
        # method -> allowed locations ("" = anywhere in package, non-def)
        "event_stream": "",
    },
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


def _defining_other(text: str, method: str) -> bool:
    """True if the method is defined (and therefore 'consumed') elsewhere."""
    return bool(re.search(rf"\.{method}\(", text))


def test_no_dead_public_methods() -> None:
    texts = _package_texts()
    for rel, methods in GUARDED.items():
        path = SRC / rel
        if not path.exists():
            continue
        for method in _collect_methods(path):
            consumed = any(
                rel != other and method in body and not _defining_other(body, method)
                for other, body in texts.items()
            )
            # a definition reference like "def event_stream" in the same file
            # is not a consumer; require an actual call elsewhere
            callers = [
                other for other, body in texts.items()
                if rel != other and re.search(rf"(?<!def )\.{method}\(", body)
            ]
            assert callers, (
                f"dead public method: {rel}::{method} has no production consumer "
                f"(only tests use it). Wire it or remove it."
            )
