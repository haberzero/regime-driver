"""regime-dialog-control.js plugin loadability tests (R4).

Guards the A-route dialog-control carrier: the opencode plugin file shipped in
the wheel (data/plugins) and its true source (.opencode/plugins) must be a
plugin opencode can actually load from an auto-scanned local plugins directory.

Two independent layers:

1. **Export-shape assertions (no node needed, always run)** — opencode's plugin
   loader (v1.18.x, `packages/opencode/src/plugin/shared.ts` `readV1Plugin`
   "detect" mode) recognizes a **default export** of the v1 form
   `{ id, server() }`; a file that only has a named export can be silently
   skipped on the auto-scan path (`{plugin,plugins}/*.{ts,js}`). These
   assertions pin the reliable shape: `export default { id, server }` plus the
   kept named export.

2. **Syntax check via node --check (skipped when node is absent)** — catches
   syntax errors before a user's opencode silently fails to load the plugin.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).parent.parent
PKG = REPO / "src" / "regime_driver"

PLUGIN_PATHS = {
    "packaged": PKG / "data" / "plugins" / "regime-dialog-control.js",
    "true_source": REPO / ".opencode" / "plugins" / "regime-dialog-control.js",
}

# The v1 plugin default-export shape opencode's loader reliably detects:
#   export default { id: "<id>", server: <fn> }
# plus the legacy named export kept for import compatibility.
_DEFAULT_EXPORT_RE = re.compile(
    r"export\s+default\s*\{[^}]*?id\s*:\s*[\"'][^\"']+[\"'][^}]*?server\s*:",
    re.S,
)
_NAMED_EXPORT_RE = re.compile(r"export\s+const\s+DialogControlPlugin\s*=")


def _plugin_text(path: Path) -> str:
    assert path.is_file(), f"plugin file missing: {path}"
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("name", sorted(PLUGIN_PATHS))
def test_plugin_file_exists(name: str):
    assert PLUGIN_PATHS[name].is_file(), f"missing plugin: {PLUGIN_PATHS[name]}"


@pytest.mark.parametrize("name", sorted(PLUGIN_PATHS))
def test_plugin_has_v1_default_export(name: str):
    """The plugin must default-export the v1 form { id, server } so opencode's
    auto-scan path reliably loads it (a named-export-only file may be skipped
    silently)."""
    text = _plugin_text(PLUGIN_PATHS[name])
    assert _DEFAULT_EXPORT_RE.search(text), (
        f"{name}: missing `export default {{ id, server }}` — opencode's "
        "auto-scan loader requires the v1 default-export form"
    )
    # the id must be the regime plugin id (not a placeholder)
    m = re.search(r"id\s*:\s*[\"']([^\"']+)[\"']", text.split("export default")[1])
    assert m and m.group(1) == "regime-dialog-control", (
        f"{name}: default export id must be 'regime-dialog-control', got "
        f"{m.group(1) if m else None!r}"
    )


@pytest.mark.parametrize("name", sorted(PLUGIN_PATHS))
def test_plugin_keeps_named_export(name: str):
    """The named export is kept for legacy/import compatibility."""
    assert _NAMED_EXPORT_RE.search(_plugin_text(PLUGIN_PATHS[name]))


def test_plugin_true_source_matches_packaged():
    """Single-source-of-truth: the shipped copy must be byte-identical to the
    true source (.opencode/plugins), so a wheel user gets exactly the reviewed
    plugin."""
    assert PLUGIN_PATHS["packaged"].read_bytes() == PLUGIN_PATHS["true_source"].read_bytes(), (
        "data/plugins/regime-dialog-control.js drifted from .opencode/plugins/"
        " — run `python ops/sync_templates.py`"
    )


def test_plugin_has_no_container_path_fallback():
    """Portability guard: the plugin must resolve `regime` purely from PATH/env
    (no host-specific or container fallback path baked in)."""
    text = _plugin_text(PLUGIN_PATHS["packaged"])
    for needle in ("/home/", "oc-meta", "miniconda", "root/control"):
        assert needle not in text, f"plugin contains host/container path: {needle!r}"


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
@pytest.mark.parametrize("name", sorted(PLUGIN_PATHS))
def test_plugin_syntax_valid_node_check(name: str):
    """The plugin must be syntactically valid JavaScript (node --check). A
    syntax error would make opencode silently fail to load it at startup."""
    proc = subprocess.run(
        [shutil.which("node"), "--check", str(PLUGIN_PATHS[name])],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, f"node --check failed for {name}:\n{proc.stderr}"
