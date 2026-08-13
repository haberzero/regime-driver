"""Config-doc drift guards (WORK_PLAN11+).

Prevents the exact breakage the 2026-08-13 audit found: new Settings fields were
added (watchdog_policy_json / auto_resume_sec) without being documented, and dead
config fields (on_stall / monitor_enabled / session_turn_check) were documented
with semantics the runtime never reads.

Guards:
  1. every Settings field is mentioned in `config.example.toml` (the config
     single-source of truth the docs point at);
  2. every field in the reference table `docs/reference/02_configuration.md`
     is a real Settings field (no phantom config keys);
  3. fields the runtime never consumes are declared `[deprecated]` in both the
     settings description and the reference table (so "dead" is explicit).
"""

from __future__ import annotations

import re
from pathlib import Path

from regime_driver.infra.settings import Settings

REPO = Path(__file__).resolve().parent.parent
CONFIG = REPO / "config.example.toml"
REF = REPO / "docs" / "reference" / "02_configuration.md"


def _settings_fields() -> dict[str, str]:
    return {name: f.description or "" for name, f in Settings.model_fields.items()}


def _mentioned_in(text: str, name: str) -> bool:
    """Field is mentioned as a whole word (avoids model↔meta_model confusion).

    Accepts a key line (`name = ...`) or a comment/example mentioning it.
    """
    return bool(re.search(rf"(?<![A-Za-z0-9_]){name}(?![A-Za-z0-9_])", text))


def _dead_fields() -> set[str]:
    """Fields declared in Settings but never consumed at runtime (audited 2026-08-13).

    monitor_enabled: preflight passes False but NOTHING reads it (the watchdog is
    always constructed); pure compatibility retention.
    """
    return {"on_stall", "monitor_poll_sec", "session_turn_check", "monitor_enabled"}


def test_every_settings_field_documented_in_config():
    cfg = CONFIG.read_text(encoding="utf-8")
    fields = _settings_fields()
    missing = [n for n in fields if not _mentioned_in(cfg, n)]
    assert not missing, (
        f"Settings fields missing from config.example.toml: {missing}\n"
        "Every Settings field must have a config.example.toml entry "
        "(the config single source of truth).")


def test_reference_table_fields_are_real_settings():
    ref = REF.read_text(encoding="utf-8")
    fields = _settings_fields()
    # only the leading column of each table row is a field name
    import re
    doc_fields = {m.group(1) for m in re.finditer(r"^\|\s*`([a-z_0-9]+)`", ref, re.M)}
    phantom = sorted(doc_fields - set(fields))
    assert not phantom, (
        f"reference table documents non-existent Settings fields: {phantom}")


def test_dead_fields_marked_deprecated():
    """Dead config fields must carry an explicit [deprecated] marker so the
    docs stop assigning them semantics the runtime never reads."""
    cfg = CONFIG.read_text(encoding="utf-8")
    ref = REF.read_text(encoding="utf-8")
    settings_desc = _settings_fields()
    for field in _dead_fields():
        assert "[deprecated]" in settings_desc[field], (
            f"dead field '{field}' not marked [deprecated] in settings.py")
        # in the reference table row that starts with `| `field` `
        if f"| `{field}`" in ref:
            row = [ln for ln in ref.splitlines()
                   if ln.lstrip().startswith(f"| `{field}`")][0]
            assert "[deprecated]" in row, (
                f"dead field '{field}' reference table row lacks [deprecated]: {row}")
        # in config.example.toml line containing the field
        lines = [ln for ln in cfg.splitlines() if field in ln]
        assert lines and "[deprecated]" in lines[0], (
            f"dead field '{field}' config line lacks [deprecated]: {lines[:1]}")


def test_watchdog_policy_fields_present():
    """The WORK_PLAN11 programmable watchdog is configurable and documented."""
    cfg = CONFIG.read_text(encoding="utf-8")
    ref = REF.read_text(encoding="utf-8")
    assert "watchdog_policy_json" in cfg
    assert "auto_resume_sec" in cfg
    assert "watchdog_policy_json" in ref
    assert "auto_resume_sec" in ref
