"""Runtime verification runner (WORK_PLAN13 + 阶段 2 W5 whitelist).

A judge node (e.g. `test`) may declare a `verify` command. When the driver
enters that judge node, it runs the command and feeds the output to the
reviewer as independent runtime evidence — closing the gap where the reviewer
(read-only, cannot execute) could only statically count tests instead of
knowing whether they actually pass.

W5 (阶段 2): the verify surface is WHITELISTED, not arbitrary host shell. A
command must be the docker-exec shape

    docker exec {container} <allowed-exec> <args...>

and is executed as an ARGV list (`shell=False`, never a host shell), so the
blast radius is bounded to the worker container and no host program / host
metacharacter can be reached. `{container}` is substituted from
settings.worker_container; the exec program must be in `VERIFY_ALLOWED_EXECS`.
A docker-group-stale shell transparently falls back to an `sg docker -c`
wrapper over the *validated, re-quoted* argv (no user-shell interpretation).

Failures/timeouts are recorded as evidence, never silently swallowed, and never
fatal on their own — the judge decides.
"""

from __future__ import annotations

import shlex
import subprocess
import time
from dataclasses import dataclass

from ..core.verify_spec import VERIFY_ALLOWED_EXECS, build_verify_argv

_TAIL = 1500


@dataclass
class VerifyResult:
    """Result of one container-side verify command."""

    ok: bool            # rc == 0
    rc: int | None
    stdout_tail: str
    stderr_tail: str
    elapsed: float
    timed_out: bool
    error: str = ""

    @property
    def failed(self) -> bool:
        return not self.ok or bool(self.error)

    def render(self) -> str:
        """Render as evidence text for the judge prompt."""
        head = f"rc={self.rc} elapsed={self.elapsed:.1f}s"
        if self.timed_out:
            head += " (TIMEOUT)"
        if self.error:
            head += f" error={self.error}"
        parts = [f"运行验证（容器内执行，{head}）："]
        if self.stdout_tail:
            parts.append(self.stdout_tail)
        if self.stderr_tail:
            parts.append(f"[stderr] {self.stderr_tail}")
        return "\n".join(parts)


def render_verify_prompt_block(result: VerifyResult, cmd: str) -> str:
    """The block appended to a judge prompt carrying runtime-verify evidence.

    A failing verification is strong objective evidence: the judge is told so
    explicitly and must NOT advance without addressing it (the semantic gate
    catches an advance that documents it as a blocking issue).
    """
    note = ""
    if result.failed:
        note = (
            "\n注意：运行验证未通过。这是客观证据——若你判定仍可推进，必须把未通过的"
            "原因以 blocking 级 issue 列出并选择不 advance（否则确定性门会拒绝）。"
        )
    return f"命令：`{cmd}`\n{result.render()}{note}"


# build_verify_argv lives in core/verify_spec.py (shared with the static
# validator); re-export for callers that imported it from here.
__all__ = ["VerifyResult", "run_verify", "render_verify_prompt_block",
           "VERIFY_ALLOWED_EXECS", "build_verify_argv"]


#: docker invocation that works in this process (direct, or `sg docker -c`
#: when the shell's docker group is stale). Cached per process.
_docker_prefix_cache_checked = False
_docker_prefix_cache: list[str] | None = None  # None = direct; else ["sg","docker","-c"]


def _docker_prefix() -> list[str]:
    """Return the working docker invocation prefix for this process.

    Probes `docker version` once; on failure (e.g. stale docker-group shell)
    every docker call is wrapped in `sg docker -c` so verify still runs.
    """
    global _docker_prefix_cache_checked, _docker_prefix_cache
    if not _docker_prefix_cache_checked:
        _docker_prefix_cache_checked = True
        try:
            p = subprocess.run(["docker", "version"], capture_output=True,
                               timeout=10)
            if p.returncode == 0:
                _docker_prefix_cache = None
            else:
                _docker_prefix_cache = ["sg", "docker", "-c"]
        except Exception:
            _docker_prefix_cache = ["sg", "docker", "-c"]
    return _docker_prefix_cache


def run_verify(cmd: str, *, container: str = "opencode-worker", timeout: float = 300.0,
               tail: int = _TAIL) -> VerifyResult:
    """Run a whitelisted verify command (argv, no host shell), substituting
    {container}. A non-whitelisted command fails loudly as evidence."""
    try:
        inner = build_verify_argv(cmd, container)
    except ValueError as exc:
        return VerifyResult(ok=False, rc=None, stdout_tail="", stderr_tail="",
                            elapsed=0.0, timed_out=False,
                            error=f"verify whitelist: {exc}")
    prefix = _docker_prefix()
    # direct argv (no shell at all) when docker is invocable; otherwise the
    # `sg docker -c <shlex.join(argv)>` wrapper re-quotes the VALIDATED argv so
    # the host shell cannot interpret any user metacharacter.
    argv = inner if prefix is None else ["sg", "docker", "-c", shlex.join(inner)]
    t0 = time.time()
    try:
        p = subprocess.run(argv, shell=False, capture_output=True, text=True,
                           timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        return VerifyResult(
            ok=False, rc=None,
            stdout_tail=(exc.stdout or b"" if isinstance(exc.stdout, bytes) else exc.stdout or "")[:tail],
            stderr_tail=(exc.stderr or b"" if isinstance(exc.stderr, bytes) else exc.stderr or "")[:tail],
            elapsed=round(time.time() - t0, 1), timed_out=True)
    except Exception as exc:  # noqa: BLE001
        return VerifyResult(
            ok=False, rc=None, stdout_tail="", stderr_tail="",
            elapsed=round(time.time() - t0, 1), timed_out=False, error=str(exc))
    return VerifyResult(
        ok=p.returncode == 0, rc=p.returncode,
        stdout_tail=(p.stdout or "")[-tail:],
        stderr_tail=(p.stderr or "")[-tail:],
        elapsed=round(time.time() - t0, 1), timed_out=False)
