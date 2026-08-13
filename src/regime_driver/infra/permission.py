"""Fine-grained permission levels for the regime CLI / Dialog Control gate.

The regime CLI contract is the single control surface. Its commands have side
effects of varying severity, so we classify each into an ordered permission
level and let an operator (human or the ``dialog-control`` agent) hold a level. Any
operation requiring a higher level than held is rejected up front — a uniform
gate shared by the CLI and the dialog carrier (对接 DialogControlUnit.allow_write).

Levels (least -> most privileged)::

    READ       introspection only (status/sessions-list/events/reply/validate/
               gate/job list/status). No side effects.
    INTERACT   + ``session send`` (talk to an opencode session).
    RUN        + ``run`` / ``run-many`` (launch workflows, incl. async jobs).
    CLEAN      + ``sessions --clean`` / ``--kill`` (destructive teardown).

Mapping to DialogControlUnit.allow_write: ``allow_write=False`` == READ;
``allow_write=True`` == CLEAN (full). See docs/subsystems/06_dialog_control.md.
"""

from __future__ import annotations

from enum import Enum


class PermissionLevel(str, Enum):
    READ = "read"
    INTERACT = "interact"
    RUN = "run"
    CLEAN = "clean"

    def __lt__(self, other: "PermissionLevel") -> bool:
        return _ORDER[self] < _ORDER[other]

    def __le__(self, other: "PermissionLevel") -> bool:
        return _ORDER[self] <= _ORDER[other]

    def __gt__(self, other: "PermissionLevel") -> bool:
        return _ORDER[self] > _ORDER[other]

    def __ge__(self, other: "PermissionLevel") -> bool:
        return _ORDER[self] >= _ORDER[other]


_ORDER = {
    PermissionLevel.READ: 0,
    PermissionLevel.INTERACT: 1,
    PermissionLevel.RUN: 2,
    PermissionLevel.CLEAN: 3,
}


class PermissionDenied(Exception):
    """Raised when an operation needs a higher permission level than held."""


# command (first non-flag arg) -> base required level
_COMMAND_LEVEL: dict[str, PermissionLevel] = {
    "status": PermissionLevel.READ,
    "sessions": PermissionLevel.READ,     # --clean/--kill escalate to CLEAN
    "events": PermissionLevel.READ,
    "session": PermissionLevel.READ,      # subcommand decides (send -> INTERACT)
    "validate": PermissionLevel.READ,
    "gate": PermissionLevel.READ,
    "preflight": PermissionLevel.READ,    # offline trial, no worker side effects
    "report": PermissionLevel.READ,
    "flow": PermissionLevel.READ,         # load/reload/rm escalate to RUN (write)
    "job": PermissionLevel.READ,          # job create via run --async is RUN
    "dialog": PermissionLevel.RUN,        # REPL enables write
    "run": PermissionLevel.RUN,
    "run-many": PermissionLevel.RUN,
    "drive": PermissionLevel.RUN,         # launches the whole self-driving stack
    "scaffold": PermissionLevel.RUN,      # writes official templates into config root
    "setup": PermissionLevel.RUN,         # guided install: deploys templates + reports
    "uninstall": PermissionLevel.CLEAN,   # deletes regime-deployed files: destructive
    "task": PermissionLevel.RUN,          # submit is RUN; stop/clean escalate to CLEAN
    "supervisor": PermissionLevel.CLEAN,  # abort/restart/human ladder: destructive
}


def classify(argv: list[str]) -> PermissionLevel:
    """Return the permission level required to run ``argv`` (a regime CLI line)."""
    tokens = [a for a in argv if a and not a.startswith("-")]
    cmd = tokens[0] if tokens else "status"
    base = _COMMAND_LEVEL.get(cmd, PermissionLevel.READ)
    flags = set(argv)

    if cmd == "sessions" and ({"--clean", "--kill", "--cleanup"} & flags):
        return PermissionLevel.CLEAN
    if cmd == "session":
        sub = tokens[1] if len(tokens) > 1 else ""
        if sub == "send":
            return PermissionLevel.INTERACT
        return PermissionLevel.READ
    if cmd == "job" and "create" in flags:
        return PermissionLevel.RUN
    if cmd == "task":
        sub = tokens[1] if len(tokens) > 1 else ""
        if sub in ("stop", "clean"):
            return PermissionLevel.CLEAN
        if sub == "submit":
            return PermissionLevel.RUN
        return PermissionLevel.READ
    if cmd == "flow":
        sub = tokens[1] if len(tokens) > 1 else ""
        if sub in ("load", "reload", "rm", "design"):
            return PermissionLevel.RUN
        return PermissionLevel.READ
    return base


def require(held: PermissionLevel, needed: PermissionLevel) -> None:
    """Raise PermissionDenied if ``held`` is insufficient for ``needed``."""
    if not (held >= needed):
        raise PermissionDenied(
            f"permission denied: '{needed.value}' required, "
            f"held '{held.value}'")


def from_dialog_control(allow_write: bool) -> PermissionLevel:
    """Map the DialogControlUnit.allow_write flag onto a permission level."""
    return PermissionLevel.CLEAN if allow_write else PermissionLevel.READ


def clamp(held: PermissionLevel, ceiling: PermissionLevel) -> PermissionLevel:
    """Cap a (possibly self-declared) held level at a configured ceiling.

    This is the "cannot self-elevate" guarantee: the ceiling comes from config/
    env, so a caller cannot raise its own held level past it.
    """
    return held if held <= ceiling else ceiling
