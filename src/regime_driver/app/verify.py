"""Runtime verification runner (WORK_PLAN13).

A judge node (e.g. `test`) may declare a `verify` shell command. When the
driver enters that judge node, it runs the command on the HOST and feeds the
output to the reviewer as independent runtime evidence — closing the gap where
the reviewer (read-only, cannot execute) could only statically count tests
instead of knowing whether they actually pass.

The command is user-authored flow config (trusted), so it runs with the host
shell. `{container}` in the command is substituted from
settings.worker_container. Failures/timeouts are recorded as evidence, never
silently swallowed, and never fatal on their own — the judge decides.
"""

from __future__ import annotations

import shlex
import subprocess
import time
from dataclasses import dataclass

_TAIL = 1500


@dataclass
class VerifyResult:
    """Result of one host-side verify command."""

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
        parts = [f"运行验证（宿主执行，{head}）："]
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


def run_verify(cmd: str, *, container: str = "opencode-worker", timeout: float = 300.0,
               tail: int = _TAIL) -> VerifyResult:
    """Run a verify command on the host (shell), substituting {container}."""
    if "{container}" in cmd:
        cmd = cmd.replace("{container}", shlex.quote(container))
    t0 = time.time()
    try:
        p = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout)
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
