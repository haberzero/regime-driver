"""Tests for the worker pool (multi opencode instance, one per workspace)."""

from __future__ import annotations

import pytest

from regime_driver.worker import (
    DockerError,
    WorkerInstance,
    WorkerPool,
    instance_name,
    slugify,
)


def test_slugify_sanitizes_and_lowercases():
    assert slugify("My Workspace!") == "my-workspace"
    assert slugify("a/b\\c") == "a-b-c"
    assert slugify("!!!") == "default"
    assert slugify("中文工作区") == "default"  # non-ASCII not valid in docker names


def test_instance_name_prefix():
    assert instance_name("algo") == "opencode-worker-algo"


def test_work_dir_for(tmp_path):
    pool = WorkerPool(workspace_root=tmp_path)
    assert pool.work_dir_for("algo") == tmp_path / "algo"


def test_container_for_roundtrip():
    pool = WorkerPool()
    assert pool.container_for("algo") == instance_name("algo")


def test_worker_instance_to_dict():
    wi = WorkerInstance("algo", "opencode-worker-algo", 4200,
                        "http://127.0.0.1:4200", "opencode-worker-algo",
                        "/ws/algo", True)
    d = wi.to_dict()
    assert d["workspace"] == "algo"
    assert d["base_url"] == "http://127.0.0.1:4200"
    assert d["healthy"] is True


class _FakeDocker:
    """In-memory docker fake: containers keyed by name -> status."""

    def __init__(self):
        self.containers = {}   # name -> "running"
        self.ports = {}        # name -> host port

    def __call__(self, args, timeout=120.0):
        cmd = args[0]
        if cmd == "ps":
            flt = args[args.index("--filter") + 1] if "--filter" in args else ""
            exact, prefix = None, None
            if flt.startswith("name="):
                val = flt[len("name="):]
                if val.startswith("^") and val.endswith("$"):
                    exact = val[1:-1]
                else:
                    prefix = val
            lines = []
            for n, st in self.containers.items():
                if exact is not None and n != exact:
                    continue
                if prefix is not None and not n.startswith(prefix):
                    continue
                lines.append(f"{n} {st}")
            from subprocess import CompletedProcess
            return CompletedProcess(args, 0, ("\n".join(lines) + "\n").encode(), b"")
        if cmd == "inspect":
            n = args[-1]
            ports = {"4097/tcp": [{"HostPort": str(self.ports.get(n, 4200))}]}
            from subprocess import CompletedProcess
            import json as _json
            return CompletedProcess(args, 0, _json.dumps(ports).encode(), b"")
        if cmd == "run":
            n = args[args.index("--name") + 1]
            self.containers[n] = "running"
            if "-p" in args:
                self.ports[n] = int(args[args.index("-p") + 1].split(":")[0])
            from subprocess import CompletedProcess
            return CompletedProcess(args, 0, b"", b"")
        if cmd == "rm":
            self.containers.pop(args[-1], None)
            from subprocess import CompletedProcess
            return CompletedProcess(args, 0, b"", b"")
        raise DockerError(f"unexpected {cmd}")


def _pool(tmp_path, fake, healthy=True):
    p = WorkerPool(workspace_root=tmp_path, api_key="k")
    p._run_docker = fake
    p._is_healthy = lambda base, timeout=5: healthy
    return p


def test_ensure_creates_and_reuses_no_duplicate(tmp_path):
    fake = _FakeDocker()
    pool = _pool(tmp_path, fake)
    wi = pool.ensure("algo")
    assert wi.container == "opencode-worker-algo"
    assert wi.work_dir == str(tmp_path / "algo")
    # second ensure reuses the SAME instance (no duplicate)
    wi2 = pool.ensure("algo")
    assert wi2.port == wi.port
    assert wi2.container == wi.container
    assert list(fake.containers) == ["opencode-worker-algo"]


def test_ensure_distinct_workspaces_distinct_instances(tmp_path):
    fake = _FakeDocker()
    pool = _pool(tmp_path, fake)
    a = pool.ensure("algo")
    b = pool.ensure("infra")
    assert a.container != b.container
    assert a.port != b.port
    assert sorted(fake.containers) == ["opencode-worker-algo", "opencode-worker-infra"]


def test_ensure_requires_key(tmp_path):
    fake = _FakeDocker()
    pool = WorkerPool(workspace_root=tmp_path, api_key=None)
    pool._run_docker = fake
    # force key resolution to be empty (independent of the host's key file/env)
    pool._resolve_key = lambda api_key: ""
    with pytest.raises(DockerError):
        pool.ensure("algo")


def test_remove_stops_and_cleans(tmp_path):
    fake = _FakeDocker()
    pool = _pool(tmp_path, fake)
    pool.ensure("algo")
    assert pool.remove("algo") is True
    assert fake.containers == {}
    # removing an absent workspace returns False
    assert pool.remove("nope") is False


def test_get_returns_instance_only_if_exists(tmp_path):
    fake = _FakeDocker()
    pool = _pool(tmp_path, fake)
    assert pool.get("algo") is None
    pool.ensure("algo")
    got = pool.get("algo")
    assert got is not None and got.workspace == "algo"
