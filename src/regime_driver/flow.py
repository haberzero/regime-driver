"""FlowRegistry — the named-flow single source of truth + hot compile/reload.

WORK_PLAN5 (F4-F6, F9-F11): the flow-definition lifecycle. Any flow — builtin
(packaged regime.json), user-designed (god dialog), or file-loaded — is a named
entry in one registry. This lets a running system:

  * hot-compile any spec (file / compact JSON / full regime dict) through one
    `compile_spec` entry (F1), which routes every source through the same
    StateMachine validation;
  * hot-reload a named flow atomically (F5/F10): the new version is compiled +
    deep-validated BEFORE it replaces the current entry; a running workflow
    already holds a reference to the old StateMachine object, which we never
    mutate, so it keeps its old snapshot mid-flight;
  * gate every load/reload on deep validation (F9) and rely on deep_validate's
    cycle detection + runtime max_total_nodes for anti-loop safety (F11).

The God Dialog's former ad-hoc `self.flows` dict is merged into this registry
(app/god_dialog.py) so there is a single source of truth for named flows.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .core.state_machine import StateMachine, StateMachineError
from .core.validate import DeepCheckResult, deep_validate
from .infra.regime_loader import load_regime


class FlowError(Exception):
    """Raised when a flow cannot be compiled/loaded/validated/reloaded."""


def default_store_dir() -> Path:
    """Default persistent flow-store directory (env-overridable, single truth)."""
    env = os.environ.get("REGIME_FLOW_STORE")
    return Path(env) if env else Path.home() / ".regime" / "flows"


@dataclass(frozen=True)
class FlowEntry:
    """An immutable snapshot of a registered named flow (versioned)."""

    name: str
    sm: StateMachine
    version: int
    source: str          # 'builtin' | 'design' | '<file path>'
    file: Path | None = None

    def to_dict(self) -> dict:
        try:
            path = list(self.sm.flow_path())
        except StateMachineError:
            path = None
        return {
            "name": self.name,
            "version": self.version,
            "source": self.source,
            "file": str(self.file) if self.file else None,
            "nodes": len(self.sm.flow.nodes),
            "path": path,
        }


def compile_spec(flow_name: str, spec_text: str) -> StateMachine:
    """Compile a workflow spec (full regime JSON or compact flow spec) into a
    validated StateMachine. The single unified entry for ALL flow sources.

    Accepts either a full regime dict (has "flows"/"entry") or a compact flow
    spec `{"entry": "start_id", "nodes": [{id, desc, role, type, next, ...}]}`.
    Raises `FlowError` on invalid/malformed input so the caller can surface a
    clean error. Pure: no file I/O.
    """
    try:
        spec = json.loads(spec_text)
    except json.JSONDecodeError as exc:
        raise FlowError(f"invalid JSON: {exc}") from exc
    if not isinstance(spec, dict):
        raise FlowError("workflow 规格必须是 JSON 对象")
    if "flows" in spec:
        regime = dict(spec)
        flows = regime["flows"]
        if flow_name not in flows:
            raise FlowError(f"flows 中找不到 '{flow_name}'")
        entry = regime.get("entry") or {
            "flow": flow_name,
            "start_node": next(iter(flows[flow_name]["nodes"])),
        }
        entry["flow"] = flow_name
        regime["entry"] = entry
        raw = json.dumps(regime)
    else:
        nodes_raw = spec.get("nodes")
        entry_id = spec.get("entry")
        if not isinstance(nodes_raw, list) or not nodes_raw:
            raise FlowError("紧凑规格需含非空 ['nodes'] 列表")
        if not entry_id:
            raise FlowError("紧凑规格需含 ['entry'] 起始节点")
        nodes: dict = {}
        for n in nodes_raw:
            if not isinstance(n, dict) or "id" not in n:
                raise FlowError("每个 node 需含 'id'")
            node = {k: n[k] for k in ("id", "desc", "role", "type") if k in n}
            for extra in ("next", "skill", "tool", "tool_args", "branches"):
                if n.get(extra) is not None:
                    node[extra] = n[extra]
            nodes[n["id"]] = node
        regime = {
            "version": "0.design",
            "meta": {"work_done_marker": "[WORK_DONE]"},
            "flows": {flow_name: {"nodes": nodes}},
            "entry": {"flow": flow_name, "start_node": entry_id},
        }
        raw = json.dumps(regime)
    try:
        return StateMachine.from_dict(raw)
    except (StateMachineError, ValueError) as exc:
        raise FlowError(str(exc)) from exc


def validate_sm(sm: StateMachine, *, skills_dir: str | Path | None = None,
                load_skill: Callable[[str], str] | None = None) -> DeepCheckResult:
    """Run the semantic deep checks over a StateMachine (F9 gate).

    `skills_dir` enables the skill-loadability check; when absent (e.g. a
    deployed container without the repo tree) we skip that check rather than
    hard-fail, matching the CLI validate behaviour.
    """
    if load_skill is None and skills_dir is not None:
        from .infra.skill_loader import load_skill as _load_skill
        load_skill = (lambda name: _load_skill(name, str(skills_dir)))
    return deep_validate(sm, load_skill=load_skill)


class FlowRegistry:
    """Named-flow single source of truth with hot load/reload semantics.

    Optional `store_dir` enables persistence: every non-builtin flow is written
    as one JSON file so separate `regime flow` invocations (and the running
    system) share the same named-flow truth. `store_dir=None` (default) keeps
    the registry in-memory only — used by tests / ephemeral contexts.
    """

    def __init__(self, builtin: StateMachine | None = None,
                 store_dir: str | Path | None = None) -> None:
        self._flows: dict[str, FlowEntry] = {}
        self._version = 0
        self._store_dir = Path(store_dir) if store_dir else None
        if builtin is not None:
            self.register(builtin.flow_name, builtin, source="builtin")
        self._load_store()

    @classmethod
    def from_default(cls, store_dir: str | Path | None = None) -> "FlowRegistry":
        """Registry seeded with the packaged regime descriptor (builtin flow)."""
        return cls(load_regime(), store_dir=store_dir)

    # -- persistence ---------------------------------------------------------

    def _store_path(self, name: str) -> Path | None:
        return (self._store_dir / f"{name}.json") if self._store_dir else None

    def _persist(self, entry: FlowEntry) -> None:
        if self._store_dir is None or entry.source == "builtin":
            return
        self._store_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "name": entry.name,
            "source": entry.source,
            "file": str(entry.file) if entry.file else None,
            "spec": entry.sm.regime.model_dump(),
        }
        self._store_path(entry.name).write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def _delete_store(self, name: str) -> None:
        p = self._store_path(name)
        if p is not None and p.exists():
            p.unlink()

    def _load_store(self) -> None:
        if self._store_dir is None or not self._store_dir.exists():
            return
        for p in sorted(self._store_dir.glob("*.json")):
            try:
                payload = json.loads(p.read_text(encoding="utf-8"))
                spec = payload.get("spec")
                if not isinstance(spec, dict):
                    continue
                sm = StateMachine.from_dict(json.dumps(spec))
                entry = FlowEntry(
                    name=payload.get("name") or sm.flow_name, sm=sm,
                    version=self._version, source=payload.get("source", "store"),
                    file=Path(payload["file"]) if payload.get("file") else None,
                )
                self._flows[entry.name] = entry
            except Exception:
                continue  # skip a corrupt entry rather than break the registry

    # -- query ---------------------------------------------------------------

    def get(self, name: str) -> FlowEntry | None:
        return self._flows.get(name)

    def sm(self, name: str) -> StateMachine | None:
        entry = self._flows.get(name)
        return entry.sm if entry else None

    def list(self) -> list[FlowEntry]:
        return sorted(self._flows.values(), key=lambda e: e.name)

    # -- mutation ------------------------------------------------------------

    def register(self, name: str, sm: StateMachine, *,
                 source: str = "design", file: Path | None = None,
                 validate: bool = False) -> FlowEntry:
        """Register a StateMachine under a name (F4).

        By default this is the low-level API that trusts the caller has already
        validated (builtin seeding). Pass `validate=True` to run the F9 deep gate
        here and reject invalid flows at the registry boundary (raises FlowError).
        """
        if validate:
            self._check(sm, preflight=False, target=name)
        self._version += 1
        entry = FlowEntry(name=name, sm=sm, version=self._version,
                          source=source, file=file)
        self._flows[name] = entry
        self._persist(entry)
        return entry

    def remove(self, name: str) -> bool:
        """Remove a named flow. Returns True if it existed and was removed.

        Running workflows already hold their StateMachine reference, so removing
        the registry entry never disrupts an in-flight workflow.
        """
        if self._flows.pop(name, None) is None:
            return False
        self._delete_store(name)
        return True

    # -- file load / atomic reload -------------------------------------------

    def load(self, path: str | Path, *, name: str | None = None,
             skills_dir: str | Path | None = None,
             preflight: bool = False) -> FlowEntry:
        """Load + validate + register a flow from a regime file (F4).

        `name` overrides the flow to register; default is the file's entry flow.
        Mandatory deep validation (F9); optional offline preflight. Raises
        FlowError (with no registry mutation) if any gate fails.
        """
        p = Path(path)
        if not p.exists():
            raise FlowError(f"regime file not found: {p}")
        try:
            sm = load_regime(p)
        except (StateMachineError, FileNotFoundError) as exc:
            raise FlowError(str(exc)) from exc
        target = name or sm.flow_name
        self._check(sm, skills_dir=skills_dir, preflight=preflight, target=target)
        return self.register(target, sm, source=str(p), file=p)

    def reload(self, name: str, *, skills_dir: str | Path | None = None,
               preflight: bool = False) -> FlowEntry:
        """Atomically reload a named flow (F5/F10).

        Re-reads the authoritative source — the backing file if file-backed,
        otherwise the persisted spec — compiles + deep-validates the new
        version, and only then swaps the registry entry (new version). A running
        workflow keeps its old StateMachine snapshot (never mutated). Raises
        FlowError (registry unchanged) if the new version is invalid.
        """
        current = self._flows.get(name)
        if current is None:
            raise FlowError(f"unknown flow '{name}' (not in registry)")
        if current.file is not None:
            return self.load(current.file, name=name, skills_dir=skills_dir,
                             preflight=preflight)
        # designed / in-memory flow: rebuild from its own persisted spec
        sm = StateMachine.from_dict(json.dumps(current.sm.regime.model_dump()))
        self._check(sm, skills_dir=skills_dir, preflight=preflight, target=name)
        return self.register(name, sm, source=current.source, file=current.file)

    # -- validation gate -----------------------------------------------------

    def _check(self, sm: StateMachine, *, skills_dir=None, preflight: bool,
               target: str) -> None:
        res = validate_sm(sm, skills_dir=skills_dir)
        if not res.ok:
            raise FlowError(
                f"flow '{target}' failed deep validation: " + "; ".join(res.errors))
        if preflight:
            from .app.preflight import preflight as _preflight
            pr = _preflight(sm, timeout_sec=30.0)
            if not pr["ok"]:
                raise FlowError(
                    f"flow '{target}' failed preflight trial: outcome={pr['outcome']} "
                    f"detail={pr['detail']!r}")
