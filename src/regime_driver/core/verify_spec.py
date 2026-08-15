"""Verify-command spec: the whitelisted docker-exec shape (W5, RCE-safe).

A judge node's `verify` command must be the shape

    docker exec {container} <allowed-exec> <args...>

so it runs as an ARGV list (`shell=False`, never a host shell) — the blast
radius is bounded to the worker container and no host program / host
metacharacter can be reached. `{container}` is substituted from
settings.worker_container; the exec program must be in `VERIFY_ALLOWED_EXECS`.

This lives in `core` (pure spec, no I/O) so BOTH the runtime runner
(`app/verify.py`) and the static validator (`core/validate.py`) share ONE
definition of the shape — a flow whose verify command is outside the whitelist
is rejected at load/validate time, not discovered mid-run (the 2026-08-14
nightly finding: a store-residual `sg docker -c` wrapper around docker-exec was
whitelist-rejected only at runtime, stalling a long task in its test gate).
"""

from __future__ import annotations

import shlex

#: Verify commands may only exec these programs INSIDE the worker container.
VERIFY_ALLOWED_EXECS = {
    "pytest", "python", "python3", "py", "node", "npm", "npx", "bash", "sh",
}


def build_verify_argv(cmd: str, container: str) -> list[str]:
    """Parse + validate a verify command into a whitelisted docker-exec argv.

    Allowed shape: `docker exec {container} <allowed-exec> <args...>` where the
    exec program is in `VERIFY_ALLOWED_EXECS`. Anything else raises `ValueError`
    (fail-fast: a non-whitelisted verify command is a config error, not a
    degraded silent run).
    """
    tokens = shlex.split(cmd)
    if len(tokens) < 4 or tokens[0] != "docker" or tokens[1] != "exec":
        raise ValueError(
            f"verify command must be 'docker exec {{container}} <whitelisted-exec> ...': {cmd!r}")
    ctr = tokens[2]
    if ctr == "{container}":
        ctr = container
    prog = tokens[3]
    if prog not in VERIFY_ALLOWED_EXECS:
        raise ValueError(
            f"verify exec '{prog}' not in whitelist {sorted(VERIFY_ALLOWED_EXECS)}")
    return ["docker", "exec", ctr, *tokens[3:]]


def verify_command_error(cmd: str, container: str = "opencode-worker") -> str | None:
    """Return the reason a verify command is outside the whitelist, or None.

    Pure, non-raising shape check — the validator's static guard. A returned
    message means the command will fail at runtime (ValueError in
    `build_verify_argv`).
    """
    try:
        build_verify_argv(cmd, container)
    except ValueError as exc:
        return str(exc)
    return None
