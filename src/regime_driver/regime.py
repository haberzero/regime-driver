"""Regime — the operating rule as a first-class object (WORK_PLAN14 阶段 1).

Root-cause A: how a task runs was fragmented across six uncoordinated carriers
(flow JSON / watchdog_policy_json / context_handover_policy_json / role policy
dataclasses / node behaviour verify+hooks / settings fields). `flow` already had
a complete lifecycle (compile -> deep_validate -> preflight -> hot-reload ->
version -> permission); the other dimensions did not. A `Regime` bundles the WHOLE
operating rule into one object with that same lifecycle:

  * flow       — the state machine (existing `StateMachine`),
  * roles      — per-role lifecycle policies (`RoleRegistry`),
  * watchdog   — the supervision policy (`WatchdogPolicy`; None = settings default),
  * handover   — the context-budget handover policy (`ContextHandoverPolicy`),
  * stall_sec / auto_resume_sec — supervision thresholds (None = settings default).

`compile_regime` / `validate_regime` give the whole rule one compile/validate
gate; `RegimeRegistry` gives named regimes a single source of truth with
persistence + atomic hot-reload (the same guarantees `FlowRegistry` gave flows).

The regime is a *declaration*: it carries no runtime environment (base_url,
model, deadlines, reporter paths stay in `Settings`). `StatechartDriver` reads
both — the regime for how to run, the settings for where/how much.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .app.handover_policy import ContextHandoverPolicy
from .app.watchdog_policy import WatchdogPolicy, policy_from_json
from .core.policy import RolePolicy, TransitionDecision
from .core.role import Role, RoleRegistry
from .core.state_machine import StateMachine, StateMachineError
from .core.validate import DeepCheckResult, deep_validate
from .flow import FlowError, compile_spec

# regime names key persistent store files — restrict the charset (no path escape)
_SAFE_NAME_RE = re.compile(r"[A-Za-z0-9._-]+")


def _check_regime_name(name: str) -> None:
    if not _SAFE_NAME_RE.fullmatch(name):
        raise FlowError(
            f"regime name {name!r} invalid: only [A-Za-z0-9._-] allowed "
            f"(it keys a persistent store file)")


@dataclass
class Regime:
    """A complete operating rule: flow + roles + supervision + handover.

    Every optional component is None-able: None means "fall back to the runtime
    default" (roles -> default_roles(), watchdog -> settings watchdog_policy_json,
    handover -> settings context_handover_policy_json, thresholds -> settings).
    """

    name: str
    flow: StateMachine
    roles: RoleRegistry | None = None
    watchdog: WatchdogPolicy | None = None
    handover: ContextHandoverPolicy | None = None
    stall_sec: float | None = None
    auto_resume_sec: float | None = None
    description: str = ""

    # -- serialization -------------------------------------------------------

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "flow": self.flow.regime.model_dump(),
            "roles": _roles_to_dict(self.roles),
            "watchdog": _policy_to_dict(self.watchdog),
            "handover": _handover_to_dict(self.handover),
            "stall_sec": self.stall_sec,
            "auto_resume_sec": self.auto_resume_sec,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Regime":
        return _regime_from_dict(data)


# ---------------------------------------------------------------------------
# compilation (one entry, one validation gate for the whole rule)
# ---------------------------------------------------------------------------

def compile_regime(spec_text: str) -> Regime:
    """Compile a full regime spec (JSON) into a validated `Regime`.

    Accepted shape::

        {
          "name": "my-regime",
          "flow": { "entry": "...", "nodes": [...] },     # compact flow spec
          "roles": { "developer": {"agent": "developer", "context_threshold_normal": 0.4} },
          "watchdog": { "soft_sec": 30, "hard_sec": 600 }, # policy_from_json shape
          "handover": { "soft_fraction": 0.5, "hard_fraction": 0.7 },
          "stall_sec": 120,
          "auto_resume_sec": 30,
        }

    Raises `FlowError` on any invalid component (flow/roles/watchdog/handover
    are each validated at parse time; the flow is additionally deep-validated by
    `validate_regime`).
    """
    try:
        spec = json.loads(spec_text)
    except json.JSONDecodeError as exc:
        raise FlowError(f"regime spec invalid JSON: {exc}") from exc
    if not isinstance(spec, dict):
        raise FlowError("regime spec must be a JSON object")
    name = str(spec.get("name") or "unnamed")
    _check_regime_name(name)
    flow_raw = spec.get("flow")
    if not isinstance(flow_raw, dict):
        raise FlowError(f"regime '{name}' requires a 'flow' object")
    # a full regime descriptor keys its flows by flow_name; align it with the
    # regime name so a later round-trip (to_dict -> from_dict) stays consistent
    # even when a file is loaded under an explicit override name.
    if "flows" in flow_raw:
        flows = flow_raw["flows"]
        if not isinstance(flows, dict):
            raise FlowError(f"regime '{name}': 'flow.flows' must be an object")
        if name not in flows:
            if len(flows) != 1:
                raise FlowError(
                    f"regime '{name}': flow descriptor has {len(flows)} flows; "
                    f"cannot auto-align to regime name")
            first = next(iter(flows))
            flows[name] = flows.pop(first)
        entry = flow_raw.get("entry")
        if isinstance(entry, dict):
            entry["flow"] = name
        # entry absent/partial: compile_spec falls back to the first flow node
    sm = compile_spec(name, json.dumps(flow_raw))
    roles = _roles_from_spec(name, spec.get("roles"))
    watchdog = _watchdog_from_spec(name, spec.get("watchdog"))
    handover = _handover_from_spec(name, spec.get("handover"))
    return Regime(
        name=name,
        flow=sm,
        roles=roles,
        watchdog=watchdog,
        handover=handover,
        stall_sec=_opt_float(spec.get("stall_sec"), name, "stall_sec"),
        auto_resume_sec=_opt_float(spec.get("auto_resume_sec"), name, "auto_resume_sec"),
        description=str(spec.get("description") or ""),
    )


def _regime_from_dict(data: dict) -> Regime:
    return compile_regime(json.dumps(data))


def validate_regime(regime: Regime, *, skills_dir: str | Path | None = None,
                    load_skill: Callable[[str], str] | None = None) -> DeepCheckResult:
    """Deep-validate the flow of a regime (roles/trusted config already gated at
    compile time). Returns issues; never raises for found issues."""
    roles = regime.roles or None
    if load_skill is None and skills_dir is not None:
        from .infra.skill_loader import load_skill as _load_skill
        load_skill = (lambda name: _load_skill(name, str(skills_dir)))
    return deep_validate(regime.flow, roles=roles, load_skill=load_skill)


# ---------------------------------------------------------------------------
# component parsers (each raises FlowError on invalid input)
# ---------------------------------------------------------------------------

def _roles_from_spec(name: str, raw) -> RoleRegistry | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise FlowError(f"regime '{name}': 'roles' must be an object keyed by role id")
    reg = RoleRegistry()
    for rid, cfg in raw.items():
        if not isinstance(cfg, dict):
            raise FlowError(
                f"regime '{name}': role '{rid}' must be an object "
                f"(agent/policy fields), got {type(cfg).__name__}")
        cfg = dict(cfg)
        agent = str(cfg.pop("agent", rid))
        policy_kwargs: dict = {}
        for fld in ("context_threshold_normal", "context_threshold_urgent",
                    "self_assess_system_prompt", "handoff_normal_template",
                    "handoff_urgent_template"):
            if fld in cfg:
                policy_kwargs[fld] = cfg.pop(fld)
        tm = cfg.pop("transition_mode", None)
        if tm is not None:
            try:
                policy_kwargs["transition_mode"] = TransitionDecision(str(tm))
            except ValueError as exc:
                raise FlowError(
                    f"regime '{name}': role '{rid}' transition_mode '{tm}' invalid "
                    f"(reuse|rotate|anchor)") from exc
        unknown = set(cfg) - {"skills_dir", "work_dir", "description"}
        if unknown:
            raise FlowError(
                f"regime '{name}': role '{rid}' unknown field(s): {sorted(unknown)}")
        role = Role(
            id=rid, agent=agent, policy=RolePolicy(**policy_kwargs),
            skills_dir=str(cfg["skills_dir"]) if cfg.get("skills_dir") else None,
            work_dir=str(cfg["work_dir"]) if cfg.get("work_dir") else None,
            description=str(cfg.get("description") or ""),
        )
        reg.register(role)
    return reg


def _watchdog_from_spec(name: str, raw) -> WatchdogPolicy | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise FlowError(f"regime '{name}': 'watchdog' must be a JSON object")
    # a declared-but-inert policy (negative/zero thresholds dropped by the
    # settings parser) would silently disable supervision — reject it loudly
    for key in ("soft_sec", "hard_sec"):
        v = raw.get(key)
        if v is not None and (isinstance(v, bool)
                              or not isinstance(v, (int, float)) or v <= 0):
            raise FlowError(f"regime '{name}': watchdog '{key}' must be a positive number")
    try:
        policy = policy_from_json(json.dumps(raw))
    except Exception as exc:
        raise FlowError(f"regime '{name}': watchdog policy invalid: {exc}") from exc
    if not policy.rules:
        raise FlowError(f"regime '{name}': watchdog policy declares no effective rules")
    return policy


def _handover_from_spec(name: str, raw) -> ContextHandoverPolicy | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise FlowError(f"regime '{name}': 'handover' must be a JSON object")
    if not raw:
        raise FlowError(
            f"regime '{name}': 'handover' is empty (an empty object would silently "
            f"enable the default policy — set \"enabled\": false to disable)")
    try:
        return ContextHandoverPolicy.from_json(json.dumps(raw))
    except Exception as exc:
        raise FlowError(f"regime '{name}': handover policy invalid: {exc}") from exc


def _opt_float(v, name: str, field_name: str) -> float | None:
    if v is None:
        return None
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise FlowError(f"regime '{name}': '{field_name}' must be a number")
    f = float(v)
    if f <= 0:
        raise FlowError(f"regime '{name}': '{field_name}' must be a positive number")
    return f


# ---------------------------------------------------------------------------
# serialization helpers
# ---------------------------------------------------------------------------

def _roles_to_dict(roles: RoleRegistry | None) -> dict | None:
    if roles is None:
        return None
    out: dict = {}
    for rid in roles.ids():
        r = roles.get(rid)
        p = r.policy
        out[rid] = {
            "agent": r.agent,
            "skills_dir": r.skills_dir,
            "work_dir": r.work_dir,
            "description": r.description,
            "context_threshold_normal": p.context_threshold_normal,
            "context_threshold_urgent": p.context_threshold_urgent,
            "self_assess_system_prompt": p.self_assess_system_prompt,
            "handoff_normal_template": p.handoff_normal_template,
            "handoff_urgent_template": p.handoff_urgent_template,
            "transition_mode": p.transition_mode.value,
        }
    return out


def _policy_to_dict(policy: WatchdogPolicy | None) -> dict | None:
    """Serialize a WatchdogPolicy back into the policy_from_json shape.

    Only rule shapes expressible in that declarative form round-trip (a Python
    plugin policy with arbitrary predicates is runtime-injected and not part of
    the declaration). The two temporal shapes map to soft_sec/hard_sec by rule
    action position on the ladder: any non-kill action (nudge/interrupt/resume/
    fallback) is the "soft" rung, kill is the "hard" backstop.
    """
    if policy is None:
        return None
    out: dict = {"name": policy.name}
    for rule in policy.rules:
        f = getattr(rule.predicate, "__closure__", None)
        seconds = None
        if f:
            for cell in f:
                if isinstance(cell.cell_contents, (int, float)) and not isinstance(
                        cell.cell_contents, bool):
                    seconds = float(cell.cell_contents)
        if seconds is None:
            continue
        if rule.action == "kill":
            out.setdefault("hard_sec", seconds)
        else:
            if "soft_sec" not in out:
                out["soft_sec"] = seconds
                out["soft_action"] = rule.action
                out["meta_gate_soft"] = bool(rule.meta)
    return out


def _handover_to_dict(policy: ContextHandoverPolicy | None) -> dict | None:
    if policy is None:
        return None
    return {
        "enabled": policy.enabled,
        "soft_fraction": policy.soft_fraction,
        "hard_fraction": policy.hard_fraction,
        "min_continue_nodes": policy.min_continue_nodes,
        "handover_keep_messages": policy.handover_keep_messages,
        "report_max_chars": policy.report_max_chars,
    }


# ---------------------------------------------------------------------------
# regime registry (named single source of truth + persistence + hot-reload)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RegimeEntry:
    """An immutable snapshot of a registered named regime (versioned)."""

    name: str
    regime: Regime
    version: int
    source: str           # 'design' | '<file path>'
    file: Path | None = None

    def to_dict(self) -> dict:
        try:
            path = list(self.regime.flow.flow_path())
        except StateMachineError:
            path = None
        return {
            "name": self.name,
            "version": self.version,
            "source": self.source,
            "file": str(self.file) if self.file else None,
            "nodes": len(self.regime.flow.flow.nodes),
            "path": path,
            "has_watchdog": self.regime.watchdog is not None,
            "has_handover": self.regime.handover is not None,
            "roles": sorted(self.regime.roles.ids()) if self.regime.roles else [],
        }


def default_regime_store_dir() -> Path:
    """Default persistent regime-store directory (env-overridable)."""
    env = os.environ.get("REGIME_STORE")
    return Path(env) if env else Path.home() / ".regime" / "regimes"


class RegimeRegistry:
    """Named-regime single source of truth with persistence + atomic hot-reload.

    Mirrors `FlowRegistry`'s guarantees at the regime level: a named regime is
    compiled + deep-validated BEFORE it replaces the current entry; a running
    workflow keeps its old `Regime` reference (never mutated), so hot-reload is
    safe mid-flight. Optional `store_dir` persists every non-builtin regime as
    one JSON file so separate CLI invocations share the same named truth.
    """

    def __init__(self, builtin: Regime | None = None,
                 store_dir: str | Path | None = None) -> None:
        self._regimes: dict[str, RegimeEntry] = {}
        self._version = 0
        self._store_dir = Path(store_dir) if store_dir else None
        if builtin is not None:
            self.register(builtin, source="builtin")
        self._load_store()

    # -- persistence ---------------------------------------------------------

    def _store_path(self, name: str) -> Path | None:
        return (self._store_dir / f"{name}.json") if self._store_dir else None

    def _persist(self, entry: RegimeEntry) -> None:
        if self._store_dir is None or entry.source == "builtin":
            return
        self._store_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "name": entry.name,
            "source": entry.source,
            "file": str(entry.file) if entry.file else None,
            "spec": entry.regime.to_dict(),
        }
        p = self._store_path(entry.name)
        # atomic write: a crash mid-write must never corrupt the only store file
        tmp = p.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, p)

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
                regime = Regime.from_dict(spec)
                entry = RegimeEntry(
                    name=payload.get("name") or regime.name, regime=regime,
                    version=self._version, source=payload.get("source", "store"),
                    file=Path(payload["file"]) if payload.get("file") else None,
                )
                self._regimes[entry.name] = entry
            except Exception:
                continue  # skip a corrupt entry rather than break the registry

    # -- query ---------------------------------------------------------------

    def get(self, name: str) -> RegimeEntry | None:
        return self._regimes.get(name)

    def regime(self, name: str) -> Regime | None:
        entry = self._regimes.get(name)
        return entry.regime if entry else None

    def list(self) -> list[RegimeEntry]:
        return sorted(self._regimes.values(), key=lambda e: e.name)

    # -- mutation ------------------------------------------------------------

    def register(self, regime: Regime, *, source: str = "design",
                 file: Path | None = None, validate: bool = False,
                 skills_dir: str | Path | None = None) -> RegimeEntry:
        """Register a Regime under its name (validates on request)."""
        _check_regime_name(regime.name)
        if validate:
            res = validate_regime(regime, skills_dir=skills_dir)
            if not res.ok:
                raise FlowError(
                    f"regime '{regime.name}' failed deep validation: "
                    + "; ".join(res.errors))
        self._version += 1
        entry = RegimeEntry(name=regime.name, regime=regime, version=self._version,
                            source=source, file=file)
        self._regimes[regime.name] = entry
        self._persist(entry)
        return entry

    def remove(self, name: str) -> bool:
        if self._regimes.pop(name, None) is None:
            return False
        self._delete_store(name)
        return True

    def load(self, path: str | Path, *, name: str | None = None,
             skills_dir: str | Path | None = None,
             preflight: bool = False) -> RegimeEntry:
        """Load + validate + register a regime from a spec file (F9 gate)."""
        p = Path(path)
        if not p.exists():
            raise FlowError(f"regime file not found: {p}")
        try:
            regime = compile_regime(p.read_text(encoding="utf-8"))
        except FlowError as exc:
            raise FlowError(f"regime file {p}: {exc}") from exc
        if name:
            # an explicit --name override is user-supplied input that keys a
            # store file: enforce the same safe-name charset as compile_regime
            _check_regime_name(name)
            regime.name = name
        self._check(regime, skills_dir=skills_dir, preflight=preflight, target=name or regime.name)
        return self.register(regime, source=str(p), file=p)

    def reload(self, name: str, *, skills_dir: str | Path | None = None,
               preflight: bool = False) -> RegimeEntry:
        """Atomically reload a named regime (compile+validate first, swap last)."""
        current = self._regimes.get(name)
        if current is None:
            raise FlowError(f"unknown regime '{name}' (not in registry)")
        if current.file is not None:
            return self.load(current.file, name=name, skills_dir=skills_dir,
                             preflight=preflight)
        spec = current.regime.to_dict()
        regime = Regime.from_dict(spec)
        self._check(regime, skills_dir=skills_dir, preflight=preflight, target=name)
        return self.register(regime, source=current.source, file=current.file)

    # -- validation gate -----------------------------------------------------

    def _check(self, regime: Regime, *, skills_dir=None, preflight: bool,
               target: str) -> None:
        res = validate_regime(regime, skills_dir=skills_dir)
        if not res.ok:
            raise FlowError(
                f"regime '{target}' failed deep validation: " + "; ".join(res.errors))
        if preflight:
            from .app.preflight import preflight as _preflight
            pr = _preflight(regime.flow, timeout_sec=30.0)
            if not pr["ok"]:
                raise FlowError(
                    f"regime '{target}' failed preflight trial: outcome={pr['outcome']} "
                    f"detail={pr['detail']!r}")
