"""Unified extension-point model (阶段 2) — the one place users inject behavior.

Regime-driver used to let operators specialize the system in three unrelated
places: a hardcoded handover prompt (W-硬编码), a global tool registry
(`core.tools.register_tool`), and a JSON-only watchdog policy. This module is
the single user-facing registry that all three channels flow through:

  * **hooks** — lifecycle callbacks (observe + side-effect) on audited hook
    points: `node_enter` / `node_done` / `transition` / `judge_verdict` /
    `stall` / `handover`. Hooks are OBSERVERS: they can log, notify, or
    customize (the `handover` hook may return a replacement document/opening),
    but they never override a deterministic verdict — the kernel keeps its
    root invariants (I1/I2/I3).
  * **rules** — watchdog policy rules (pure predicates), merged into the
    running `WatchdogPolicy` alongside JSON-declared rules.
  * **tools** — custom deterministic tools for TOOL nodes (delegated to the
    existing `core.tools` registry).

A user plugin is a Python module at `~/.regime/hooks.py` (env `REGIME_HOOKS`
overrides the path) defining `register(registry)`:

    # ~/.regime/hooks.py
    def register(reg):
        @reg.hook("node_done")                      # decorator form
        def on_done(ctx): ...

        def on_stall(ctx): ...                      # or explicit form
        reg.register_hook("stall", on_stall)

        def never_busy(ev): return False
        reg.register_rule("never-busy", never_busy, "nudge", reason="demo")

        reg.register_tool("ping", lambda c, r, a: _ToolResult(True, "pong"))

Load-time errors (bad import / missing `register`) fail loudly; a runtime hook
error is recorded as `hook_error` and never kills the governed loop (the same
contract as a broken watchdog rule).

Everything is deterministic + testable: `HookRegistry` is pure bookkeeping;
`load_user_hooks` is the only file I/O.
"""

from __future__ import annotations

import importlib.util
import logging
import os
from collections import defaultdict
from pathlib import Path
from typing import Callable

from .app.watchdog_policy import Rule

log = logging.getLogger(__name__)

#: The audited lifecycle hook points. A hook fires with a context dict; the
#: `handover` hook is override-capable (may return {"document":..., "opening":...}).
HOOK_POINTS = (
    "node_enter",
    "node_done",
    "transition",
    "judge_verdict",
    "stall",
    "handover",
)


def default_hooks_path() -> Path:
    """The user extension module path (env `REGIME_HOOKS` overrides ~/.regime/hooks.py)."""
    env = os.environ.get("REGIME_HOOKS")
    return Path(env) if env else Path.home() / ".regime" / "hooks.py"


class HookError(Exception):
    """A user hook raised at runtime. Recorded, never fatal to the loop."""


class HookRegistry:
    """The unified extension registry (hooks + watchdog rules + tools).

    `register_hook` / `register_rule` / `register_tool` are the three channels a
    user plugin injects behavior through; `fire` runs the hooks for a point
    (collecting returns, never letting a hook error kill the caller); `rules`
    and `tools` are consumed by the driver / tool runner.
    """

    def __init__(self) -> None:
        self._hooks: dict[str, list[Callable]] = defaultdict(list)
        self.rules: list[Rule] = []
        self.tools: dict[str, Callable] = {}
        self.source: Path | None = None   # the loaded plugin path (None = empty)

    # -- registration ---------------------------------------------------------

    def register_hook(self, point: str, fn: Callable) -> None:
        """Register a lifecycle hook. Unknown points fail loudly at load time."""
        if point not in HOOK_POINTS:
            raise ValueError(
                f"unknown hook point '{point}' (available: {', '.join(HOOK_POINTS)})")
        self._hooks[point].append(fn)

    def hook(self, point: str):
        """Decorator form of `register_hook`."""
        def _wrap(fn: Callable) -> Callable:
            self.register_hook(point, fn)
            return fn
        return _wrap

    def register_rule(self, name: str, predicate: Callable, action: str, *,
                      meta: bool = False, reason: str = "") -> None:
        """Register a watchdog policy rule (a pure `SessionEvidence -> bool`
        predicate). Its action must be on the policy ladder the watchdog walks;
        that is validated when the rules are merged into the policy."""
        self.rules.append(Rule(
            name=name, predicate=predicate, action=action, meta=meta, reason=reason))

    def register_tool(self, name: str, fn: Callable) -> None:
        """Register a deterministic tool for TOOL nodes (delegated to the
        existing `core.tools` registry the kernel reads)."""
        from .core import tools as _tools
        _tools.TOOLS[name] = fn
        self.tools[name] = fn

    # -- consumption ----------------------------------------------------------

    def fire(self, point: str, on_error: Callable[[str, Exception], None] | None = None,
             **ctx) -> list:
        """Run every hook registered for `point` with `ctx`; return their returns.

        A hook error is delivered to `on_error` (e.g. the unit's `_log`) when
        given and otherwise logged — it never propagates (a broken user
        extension must not kill the governed loop). Non-None returns are
        collected so an override-capable hook (handover) can customize.
        """
        results: list = []
        for fn in list(self._hooks.get(point, ())):
            try:
                r = fn(ctx)
                if r is not None:
                    results.append(r)
            except Exception as exc:  # a broken user hook must not kill the loop
                if on_error is not None:
                    on_error(point, exc)
                else:
                    log.warning("hook %s error: %s", point, exc)
        return results

    def hooks_for(self, point: str) -> list[Callable]:
        return list(self._hooks.get(point, ()))

    # -- introspection (dialog `hook list`) -----------------------------------

    def summary(self) -> dict:
        return {
            "source": str(self.source) if self.source else None,
            "points": {p: len(self._hooks.get(p, ())) for p in HOOK_POINTS},
            "rules": [r.name for r in self.rules],
            "tools": sorted(self.tools),
        }

    # -- reload ---------------------------------------------------------------

    def reload(self, path: Path | str | None = None) -> "HookRegistry":
        """Reload the plugin module into a FRESH registry (atomic swap).

        The old registry's registered tools are removed from the global
        `core.tools` registry so the tools channel is reload-atomic too (no
        stale plugin tools leaking after a reload). Returns the new registry;
        the caller replaces its reference (running units keep their old
        registry snapshot — never mutated mid-flight).
        """
        from .core import tools as _tools

        for name in self.tools:
            _tools.TOOLS.pop(name, None)
        return load_user_hooks(path or self.source or default_hooks_path())


def load_user_hooks(path: Path | str | None = None) -> HookRegistry:
    """Load the user extension module into a fresh `HookRegistry`.

    A missing plugin file is not an error (empty registry). A plugin that fails
    to import or lacks `register(reg)` fails loudly (fail-fast: an operator's
    extension config must surface immediately, not silently degrade).
    """
    p = Path(path) if path is not None else default_hooks_path()
    reg = HookRegistry()
    if not p.exists():
        return reg
    spec = importlib.util.spec_from_file_location("regime_user_hooks", p)
    if spec is None or spec.loader is None:
        raise HookError(f"cannot load user hooks module from {p}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # import errors raise loudly here
    register = getattr(module, "register", None)
    if not callable(register):
        raise HookError(
            f"user hooks module {p} must define register(registry)")
    register(reg)
    reg.source = p
    return reg
