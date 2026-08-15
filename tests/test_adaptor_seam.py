"""Adaptor-seam guard: kernel modules reach the agent transport ONLY via the
DriveClient protocol (``infra/drive_client.py``).

Prevents the adaptor-layer debt from creeping back: after the interface
extraction, no kernel module may import ``infra/opencode.py`` directly —
``Message``/``OpenCodeError``/``is_abort_error`` are re-exported by
``infra/drive_client.py`` for kernel use, and ``OpenCodeClient`` is touched
only at construction sites (where the concrete adapter is chosen).
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).parent.parent / "src" / "regime_driver"

# kernel modules: app/ + core/ + top-level orchestrators
KERNEL = sorted(
    [p for p in (SRC / "app").glob("*.py")]
    + [p for p in (SRC / "core").glob("*.py")]
    + [SRC / p for p in ("drive.py", "supervisor.py", "parallel.py",
                        "task.py", "flow.py", "regime.py")]
)

# construction sites: these choose the concrete adapter, everything else is
# protocol-typed.
CONSTRUCTION_SITES = {
    "app/dialog_app.py",   # builds OpenCodeClient for the dialog window
    "parallel.py",         # builds one OpenCodeClient per worker instance
}

_IMPORT_RE = re.compile(r"^\s*from\s+(?:\.\.?)?infra\.opencode\s+import\s+(.+)$")


def test_kernel_imports_transport_only_via_drive_client():
    offenders = []
    for path in KERNEL:
        rel = path.relative_to(SRC).as_posix()
        if rel in CONSTRUCTION_SITES:
            continue
        for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            m = _IMPORT_RE.match(line)
            if m:
                offenders.append(f"{rel}:{lineno}: {line.strip()}")
    assert not offenders, (
        "kernel modules must not import infra/opencode.py directly — use "
        "infra/drive_client.py (Message/OpenCodeError/is_abort_error re-exports "
        "or the DriveClient protocol). Found:\n" + "\n".join(offenders))


def test_drive_client_reexports_transport_surface():
    """The seam re-exports the transport-neutral surface for kernel use."""
    from regime_driver.infra.drive_client import (
        DriveClient, Message, OpenCodeError, is_abort_error,
    )
    assert Message.__name__ == "Message"
    assert issubclass(OpenCodeError, Exception)
    assert callable(is_abort_error)
    # the protocol itself is a structural, runtime-checkable type
    assert DriveClient is not None
