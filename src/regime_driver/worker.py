"""Worker pool: multiple opencode instances, one per workspace (isolation by instance).

Architecture pivot (2026-08-09, per directive): per-SESSION workspace isolation is
impossible with this opencode version — the `directory` field on create_session is
project-level and ignored (verified: always resolves to the server's cwd). So we
achieve physical workspace isolation by launching **multiple opencode instances**,
one per workspace:

  * each workspace -> exactly ONE opencode worker instance (its own container,
    own mounted workspace directory, own port);
  * the same workspace never spawns a duplicate instance (the no-duplicate
    invariant — enforced by querying docker, so it holds across processes);
  * within a workspace instance, roles (developer/reviewer/dialog-control) are still
    distinguished as SESSIONS (the normal per-role session model).

This replaces the old single shared worker that all workflows wrote to (collision
risk). `WorkerPool.ensure(ws)` allocates/returns the instance for a workspace;
`regime drive --workspace <ws>` runs the whole stack against that instance.

The mapping workspace->instance is persistent via docker (container names) so the
no-duplicate invariant survives process restarts. Pure helpers (slug/name/port)
are offline-testable; docker operations use a shell-safe `docker`/`sg docker`
fallback (stale-shell docker-group, matching ops/up.sh and Supervisor.docker_restart).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .infra.opencode import OpenCodeClient

DEFAULT_WORKSPACE_ROOT = os.environ.get(
    "REGIME_WORKSPACE_ROOT", str(Path.home() / "oc-meta" / "workspaces"))
DEFAULT_IMAGE = os.environ.get("REGIME_WORKER_IMAGE", "opencode-worker:1.18.11")
DEFAULT_PORT_BASE = int(os.environ.get("REGIME_WORKER_PORT_BASE", "4200"))
DEFAULT_MAX_INSTANCES = os.environ.get("REGIME_WORKER_MAX_INSTANCES")


def slugify(workspace: str) -> str:
    """Deterministic safe container-name token for a workspace."""
    s = re.sub(r"[^a-zA-Z0-9_.-]", "-", workspace.strip().lower())
    s = re.sub(r"-+", "-", s).strip("-")
    return s or "default"


def instance_name(workspace: str) -> str:
    return f"opencode-worker-{slugify(workspace)}"


class DockerError(Exception):
    """Raised when a docker operation fails at the transport level."""


def _run_docker(args: list[str], timeout: float = 120.0) -> subprocess.CompletedProcess:
    """Run a docker command, falling back to `sg docker -c` for a stale docker-group shell.

    The host shell may be in a pre-docker-group session (see HANDOVER §3); plain
    `docker` fails with permission, so we retry through `sg docker -c`. Each arg is
    shell-quoted so multi-word values (e.g. `--format "{{.Names}} {{.Status}}"`)
    survive the `sg ... -c` shell.
    """
    import shlex

    shell_cmd = "docker " + " ".join(shlex.quote(a) for a in args)
    candidates = [
        ["docker", *args],
        ["sg", "docker", "-c", shell_cmd],
    ]
    last = None
    for cmd in candidates:
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=timeout)
            if proc.returncode == 0:
                return proc
            last = proc
        except Exception as exc:
            last = subprocess.CompletedProcess(cmd, 1, b"", str(exc).encode())
    raise DockerError(
        f"docker {' '.join(args)} failed: "
        f"{(last.stderr or b'').decode(errors='ignore').strip()[:300]}"
        if last else "docker unavailable")


@dataclass
class WorkerInstance:
    """One opencode instance bound to one workspace."""

    workspace: str
    name: str
    port: int
    base_url: str
    container: str
    work_dir: str
    healthy: bool = False

    def to_dict(self) -> dict:
        return {
            "workspace": self.workspace,
            "name": self.name,
            "port": self.port,
            "base_url": self.base_url,
            "container": self.container,
            "work_dir": self.work_dir,
            "healthy": self.healthy,
        }


class WorkerPool:
    """Manage the workspace->opencode-instance mapping (no duplicate per workspace).

    The mapping is persistent (docker container names), so the no-duplicate
    invariant holds across processes and the caller's lifetime.
    """

    def __init__(
        self,
        *,
        workspace_root: str | Path = DEFAULT_WORKSPACE_ROOT,
        image: str = DEFAULT_IMAGE,
        port_base: int = DEFAULT_PORT_BASE,
        api_key: str | None = None,
        health_poll_sec: float = 2.0,
        max_instances: int | None = None,
    ) -> None:
        self.workspace_root = Path(workspace_root)
        self.image = image
        self.port_base = port_base
        self.api_key = api_key
        self.health_poll_sec = health_poll_sec
        self.max_instances = (int(max_instances) if max_instances is not None
                              else (int(DEFAULT_MAX_INSTANCES)
                                    if DEFAULT_MAX_INSTANCES else None))

    # -- docker dispatch (method so tests can substitute a fake) -------------

    def _run_docker(self, args: list[str], timeout: float = 120.0):
        """Run a docker command with the stale-shell `sg docker` fallback."""
        return _run_docker(args, timeout=timeout)

    # -- pure helpers (offline-testable) -------------------------------------

    def container_for(self, workspace: str) -> str:
        return instance_name(workspace)

    def work_dir_for(self, workspace: str) -> Path:
        return self.workspace_root / slugify(workspace)

    # -- docker-backed operations --------------------------------------------

    def _container_status(self, name: str) -> str | None:
        """Return 'running'/'exited'/etc for a container, or None if absent."""
        try:
            proc = self._run_docker(["ps", "-a", "--filter", f"name=^{name}$",
                                "--format", "{{.Names}} {{.Status}}"], timeout=30)
            for line in proc.stdout.decode(errors="ignore").splitlines():
                parts = line.split()
                if parts and parts[0] == name:
                    return parts[1] if len(parts) > 1 else "running"
        except DockerError:
            pass
        return None

    def _port_of(self, name: str) -> int | None:
        """Read the host port of an existing container (0.0.0.0:PORT->4097)."""
        try:
            proc = self._run_docker(["inspect", "--format", "{{json .NetworkSettings.Ports}}",
                                name], timeout=30)
            data = json.loads(proc.stdout.decode(errors="ignore") or "{}")
        except (DockerError, json.JSONDecodeError):
            return None
        for key, bindings in data.items():
            if key.endswith("/tcp"):
                for b in bindings or []:
                    hp = (b or {}).get("HostPort")
                    if hp:
                        try:
                            return int(hp)
                        except ValueError:
                            continue
        return None

    def _free_port(self) -> int:
        """Find the first free host port at/after port_base (excluding in-use)."""
        used = {self._port_of(f"opencode-worker-{slugify(ws)}")
                for ws in self.list_workspaces()} | {None}
        p = self.port_base
        while True:
            if p not in used and not self._port_in_use(p):
                return p
            p += 1

    @staticmethod
    def _port_in_use(port: int) -> bool:
        import socket
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex(("127.0.0.1", port)) == 0

    def list_workspaces(self) -> list[str]:
        """Return workspace ids that currently have an opencode-worker-* instance."""
        try:
            proc = self._run_docker(["ps", "-a", "--filter", "name=opencode-worker-",
                                "--format", "{{.Names}}"], timeout=30)
        except DockerError:
            return []
        out = []
        for line in proc.stdout.decode(errors="ignore").splitlines():
            name = line.strip()
            if not name or name == "opencode-worker" or not name.startswith("opencode-worker-"):
                continue
            out.append(name[len("opencode-worker-"):])
        return out

    # -- main API -------------------------------------------------------------

    def get(self, workspace: str) -> WorkerInstance | None:
        """Return the existing instance for a workspace, or None (no duplicate)."""
        name = self.container_for(workspace)
        if self._container_status(name) is None:
            return None
        port = self._port_of(name) or self._alloc_stable_port(workspace)
        work_dir = str(self.work_dir_for(workspace))
        base = f"http://127.0.0.1:{port}"
        healthy = self._is_healthy(base)
        return WorkerInstance(workspace, name, port, base, name, work_dir, healthy)

    def _alloc_stable_port(self, workspace: str) -> int:
        # deterministic fallback when inspect can't read the port (shouldn't happen
        # for a running container); base on a stable hash within a wide range
        return self.port_base + (sum(bytearray(slugify(workspace).encode())) % 500)

    def _is_healthy(self, base_url: str, timeout: float = 5.0) -> bool:
        try:
            return OpenCodeClient(base_url, timeout=timeout).health()
        except Exception:
            return False

    @staticmethod
    def _read_key_file(name: str) -> str:
        kf = Path.home() / ".regime" / "keys" / name
        if kf.exists():
            try:
                return kf.read_text(encoding="utf-8").strip()
            except OSError:
                return ""
        return ""

    @classmethod
    def _resolve_keys(cls) -> dict[str, str]:
        """Resolve model API keys for a launched worker.

        Sources (per key): explicit env var > `~/.regime/keys/<name>.key`. This
        keeps keys OUT of configs/images (never committed): the container only
        receives them as env vars at runtime.
        """
        out: dict[str, str] = {}
        for env_name, file_name in (
            ("DEEPSEEK_API_KEY", "deepseek.key"),
            ("OPENCODE_GO_API_KEY", "opencode-go.key"),
        ):
            val = os.environ.get(env_name) or cls._read_key_file(file_name)
            if val:
                out[env_name] = val
        return out

    def ensure(self, workspace: str) -> WorkerInstance:
        """Return the instance for a workspace, creating it if absent.

        Enforces the no-duplicate invariant: if an instance already exists for the
        workspace, it is reused (never a second one). Returns the instance.
        """
        existing = self.get(workspace)
        if existing is not None:
            return existing
        if self.max_instances is not None and len(self.list()) >= self.max_instances:
            raise DockerError(
                f"max_instances={self.max_instances} reached ({len(self.list())} running); "
                f"prune idle instances (`regime worker prune`) or raise the cap")
        name = self.container_for(workspace)
        work_dir = self.work_dir_for(workspace)
        work_dir.mkdir(parents=True, exist_ok=True)
        port = self._free_port()
        # explicit constructor key wins; otherwise fall back to env/key files.
        # (fixes the dead `api_key` param and makes launch hermetic in CI, where
        # there is no host ~/.regime/keys file.)
        keys = self._resolve_keys()
        if self.api_key:
            keys.setdefault("OPENCODE_GO_API_KEY", self.api_key)
        if not keys:
            raise DockerError(
                "no model API key to launch a worker instance (set DEEPSEEK_API_KEY / "
                "OPENCODE_GO_API_KEY or write ~/.regime/keys/*.key)")
        # The worker MUST run as root: its home is /root and opencode needs to
        # write there; running as a non-root user breaks session creation (HTTP
        # 500). Consequence: workspace files written by the container are
        # root-owned. To keep them host-manageable, `remove()`/`clean()` chown
        # the workspace back to the host uid:gid via a throwaway root container.
        env_args: list[str] = []
        for env_name, val in keys.items():
            env_args += ["-e", f"{env_name}={val}"]
        self._run_docker([
            "run", "-d", "--name", name,
            "-p", f"{port}:4097",
            "-v", f"{work_dir}:/root/work",
            *env_args,
            self.image,
        ])
        # wait for health (bounded)
        base = f"http://127.0.0.1:{port}"
        deadline = time.time() + 120
        while time.time() < deadline:
            if self._is_healthy(base):
                return WorkerInstance(workspace, name, port, base, name,
                                      str(work_dir), True)
            time.sleep(self.health_poll_sec)
        raise DockerError(f"worker instance {name} did not become healthy in 120s")

    def remove(self, workspace: str) -> bool:
        """Stop + remove the instance for a workspace. Returns True if removed.

        Before removing, chowns the (root-owned) workspace back to the host
        uid:gid via a throwaway root container, so the host user can manage/clean
        the workspace files afterwards.
        """
        name = self.container_for(workspace)
        if self._container_status(name) is None:
            return False
        try:
            self._run_docker(["rm", "-f", name], timeout=60)
        except DockerError:
            return False
        self._chown_workspace(workspace)
        return True

    def _chown_workspace(self, workspace: str) -> None:
        """Best-effort: chown the workspace to the host uid:gid via root container."""
        work_dir = self.work_dir_for(workspace)
        if not work_dir.exists():
            return
        try:
            self._run_docker([
                "run", "--rm", "--entrypoint", "/bin/chown",
                "-v", f"{work_dir}:/w",
                self.image, "-R", f"{os.getuid()}:{os.getgid()}", "/w",
            ], timeout=120)
        except DockerError:
            pass  # best-effort; workspace stays root-owned if chown fails

    def list(self) -> list[WorkerInstance]:
        return [self.get(ws) for ws in self.list_workspaces() if self.get(ws) is not None]

    def gc_idle(self, max_idle_sec: float = 300.0, dry_run: bool = False) -> list[str]:
        """Reclaim idle instances: healthy instances with NO sessions at all.

        An instance that has no opencode sessions (nothing running, nothing to
        resume) is considered idle and can be reclaimed to bound resource growth
        of the parallel batch. With `dry_run=True` only reports (does not remove). Returns
        the workspaces reclaimed.
        """
        reclaimed = []
        for ws in self.list_workspaces():
            inst = self.get(ws)
            if inst is None or not inst.healthy:
                continue
            try:
                sessions = OpenCodeClient(inst.base_url, timeout=10).list_sessions()
            except Exception:
                continue
            if sessions:
                continue  # still has sessions -> not idle
            if not dry_run:
                self.remove(ws)
            reclaimed.append(ws)
        return reclaimed
