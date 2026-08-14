"""Programmable watchdog policy (WORK_PLAN11) — the config layer.

The watchdog is no longer a hardcoded "busy-without-progress > stall_sec ->
STOP". It is a small policy engine: a `WatchdogPolicy` declares which signals
to probe, which rules decide the response, and which action ladder to execute.
Everything is injectable so an operator can adapt the watchdog to their own
detection heuristics without touching core code.

Model (four layers):

  1. **Evidence** — the raw facts a probe collects about a working session:
     SSE-activity timestamp, latest message timestamps, current node/phase,
     session status, wall-clock time, ... carried in the REPORT payload.
  2. **Probe** — a pure function `Evidence -> richer evidence` (I/O-free). The
     workflow already collects the base facts; probes derive signals from them.
  3. **Rule** — `(name, predicate: Evidence -> bool, action, meta: bool)`.
     Predicates are pure and injectable; `meta=True` routes the hit to the
     intelligent reviewer (meta-analysis) before acting.
  4. **Ladder** — the ordered response: `nudge` (light), `interrupt` (pause the
     session, keep it for natural recovery), `resume` (inject "continue"),
     `fallback` (switch model), `kill` (final, destructive backstop). Only the
     final ladder rung is destructive; earlier rungs prefer recovery.

Everything is deterministic + testable: `WatchdogPolicy.decide(evidence)`
returns the action to take, and `Ladder.next()` bounds escalation so a
`kill` can only ever follow earlier non-destructive rungs.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Callable


# -- ladder actions (ordered, escalation-bounded) ------------------------------

L1_NUDGE = "nudge"              # light: poke the session, keep waiting
L2_INTERRUPT = "interrupt"      # PAUSE: abort the current generation, keep session
L3_RESUME = "resume"            # RESUME: inject "continue" to resume naturally
L4_FALLBACK = "fallback"        # switch model and retry
L5_KILL = "kill"                # final destructive backstop (stop session + workflow)

LADDER_ORDER = (L1_NUDGE, L2_INTERRUPT, L3_RESUME, L4_FALLBACK, L5_KILL)


@dataclass
class Ladder:
    """Ordered action ladder. Escalation moves strictly forward; a recovery
    (evidence that the session resumed) resets to the first rung.

    ``fired`` records which rung's action has already been emitted for the
    current episode, so a repeated hit at the same rung (no recovery) fires
    only once.

    ``order`` is the action vocabulary this ladder walks. Defaults to the
    unified in-process vocabulary; a process-external Actor with a different
    capability set (docker restart / human escalation) declares its own order
    (phase-1c: the judgment engine is shared, the action set is per-Actor
    capability).
    """

    index: int = 0
    fired: int = -1  # -1 = nothing emitted yet this episode
    order: tuple = LADDER_ORDER

    def current(self) -> str:
        return self.order[min(self.index, len(self.order) - 1)]

    def advance(self) -> str:
        """Escalate one rung (does not wrap). Returns the new current action."""
        if self.index < len(self.order) - 1:
            self.index += 1
        return self.current()

    def reset(self) -> str:
        self.index = 0
        self.fired = -1
        return self.current()

    def should_fire(self) -> bool:
        """True if the current rung's action has not yet been emitted."""
        if self.index != self.fired:
            self.fired = self.index
            return True
        return False


# -- evidence + probes ---------------------------------------------------------

@dataclass
class SessionEvidence:
    """All facts the watchdog can reason over for one session."""

    session_id: str
    status: str | None = None           # busy / idle / None
    activity_ts: float = 0.0            # last SSE progress (wall clock)
    latest_message_ts: float = 0.0      # last assistant message timestamp
    latest_message_age: float = 0.0     # seconds since the last assistant message
    node: str | None = None             # current node id
    phase: str | None = None            # agent_wait / judge_wait / ...
    now: float = 0.0                    # wall clock at evidence time
    first_busy_ts: float = 0.0          # when this busy window began (fallback base)
    consecutive_stalls: int = 0         # stall windows already seen
    paused: bool = False                # deliberately interrupted, awaiting RESUME
    meta: dict = field(default_factory=dict)  # extra operator-provided facts

    def busy(self) -> bool:
        return self.status == "busy"

    def silent_for(self) -> float:
        """Seconds since the last liveness signal.

        Uses the MOST RECENT of the SSE-activity timestamp and the latest
        message timestamp (a new message is fresher liveness than old SSE);
        falls back to the first-busy observation when neither exists, so a
        busy-but-entirely-silent session still stalls.
        """
        base = max(self.activity_ts, self.latest_message_ts) or self.first_busy_ts
        if not base:
            return 0.0
        return max(0.0, self.now - base)


# Predicate: (evidence) -> bool. Pure, injectable.
Predicate = Callable[[SessionEvidence], bool]


@dataclass
class Rule:
    """One decision rule: when `predicate` holds, take `action`.

    `meta=True` means the hit must be confirmed by the intelligent reviewer
    (meta-analysis) before the action is executed — a soft trigger becomes a
    hard action only after an independent agent judged the evidence.
    """

    name: str
    predicate: Predicate
    action: str
    meta: bool = False
    reason: str = ""


# -- the policy ----------------------------------------------------------------

@dataclass
class WatchdogPolicy:
    """Declarative, injectable watchdog behaviour.

    `probes` are optional enrichments applied to the raw evidence before rules
    run. Among all rules that fire, the MOST severe action wins (the one highest
    on the ladder), so a soft rule can never mask a hard rule that also applies.
    Escalation is tracked **per session** (each session gets its own `Ladder`)
    so one stuck session never advances another's ladder, and a repeated hit at
    the same rung for the same session fires only once (the fired guard) until
    it recovers.

    `actions` is the ladder vocabulary this policy walks (default: the unified
    in-process actions). Actors with a different capability set declare their
    own order — the judgment engine (rules -> decide -> ladder -> fired-guard ->
    recovery-reset) is shared, only the action vocabulary differs.

    A rule with `meta=True` is meta-gated: the policy returns ``"meta:<action>"``
    so the caller can route the hit to an independent reviewer (e.g. the
    supervisor's meta_analyze) for confirmation before acting.
    """

    rules: list[Rule] = field(default_factory=list)
    probes: list[Callable[[SessionEvidence], SessionEvidence]] = field(default_factory=list)
    name: str = "default"
    actions: tuple = LADDER_ORDER
    _ladders: dict[str, "Ladder"] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        # an operator typo (action not on the ladder) must fail loudly at
        # construction, not silently degrade to a light nudge at runtime.
        for rule in self.rules:
            if rule.action not in self.actions:
                raise ValueError(
                    f"rule '{rule.name}' action {rule.action!r} not in "
                    f"ladder {self.actions}")

    def _ladder_for(self, session_id: str) -> "Ladder":
        return self._ladders.setdefault(session_id, Ladder(order=self.actions))

    def enrich(self, ev: SessionEvidence) -> SessionEvidence:
        for probe in self.probes:
            ev = probe(ev)
        return ev

    def decide(self, ev: SessionEvidence, *, recovered: bool = False) -> str | None:
        """Return the action to take (None = do nothing), updating the ladder.

        `recovered=True` (the session resumed) resets escalation. Among all
        rules that fire, the MOST severe action wins (the one highest on the
        ladder), so a soft rule can never mask a hard rule that also applies.

        A rule with `meta=True` is meta-gated: the policy reports
        ``"meta:<action>"`` so the caller can route the hit to an independent
        reviewer (e.g. the supervisor's meta_analyze) for confirmation BEFORE
        acting — but only when that action is proposed solely by meta rules. If
        a non-meta (deterministic) rule also proposes the same action, the
        deterministic floor already holds and it acts directly: meta is a gate,
        never a mask for a harder deterministic rule.
        The session's ladder then climbs to that rung; a repeated hit at the
        same rung (no recovery) fires only once.
        """
        ev = self.enrich(ev)
        ladder = self._ladder_for(ev.session_id)
        if recovered:
            ladder.reset()
            return None
        hits: list[str] = []
        meta_hits: list[str] = []
        for rule in self.rules:
            try:
                if rule.predicate(ev):
                    if rule.meta:
                        meta_hits.append(rule.action)
                    else:
                        hits.append(rule.action)
            except Exception:  # a broken operator rule must not kill the loop
                continue
        candidates = hits + meta_hits
        if not candidates:
            return None
        # rule actions are validated against self.actions at construction, so
        # the severity lookup is total (no dead defensive `else`).
        action = max(candidates, key=lambda a: self.actions.index(a))
        gated = action in meta_hits and action not in hits
        self._climb_to(ladder, action)
        if not ladder.should_fire():
            return None  # fired once for this session, no recovery
        return f"meta:{action}" if gated else action

    def _climb_to(self, ladder: "Ladder", action: str) -> None:
        target = self.actions.index(action) if action in self.actions else 0
        while ladder.index < target:
            ladder.advance()


# -- convenience predicates (pure, reusable) -----------------------------------

def no_activity_for(seconds: float) -> Predicate:
    def _p(ev: SessionEvidence) -> bool:
        return ev.busy() and ev.silent_for() >= seconds
    return _p


def no_message_for(seconds: float) -> Predicate:
    def _p(ev: SessionEvidence) -> bool:
        return ev.busy() and (ev.latest_message_age or ev.silent_for()) >= seconds
    return _p


def deadline_reached(seconds: float) -> Predicate:
    def _p(ev: SessionEvidence) -> bool:
        return ev.silent_for() >= seconds
    return _p


def policy_from_json(raw: str | None) -> "WatchdogPolicy":
    """Build a WatchdogPolicy from an operator JSON string (empty/None -> None).

    Supported shape:
        {
          "soft_sec": 30,          # busy + no liveness -> soft_action
          "soft_action": "interrupt",  # nudge | interrupt | resume | fallback | kill
          "meta_gate_soft": true,  # gate the soft action behind intelligent review
          "hard_sec": 600,         # busy + no liveness -> kill (final backstop)
          "name": "my-policy"
        }
    Returns None for empty input so callers can fall back to the default policy.
    """
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    name = str(data.get("name") or "operator")
    rules: list[Rule] = []
    soft_sec = data.get("soft_sec")
    if isinstance(soft_sec, (int, float)) and soft_sec > 0:
        soft_action = str(data.get("soft_action") or L2_INTERRUPT)
        rules.append(Rule(
            name=f"{name}-soft",
            predicate=no_activity_for(float(soft_sec)),
            action=soft_action,
            meta=bool(data.get("meta_gate_soft")),
        ))
    hard_sec = data.get("hard_sec")
    if isinstance(hard_sec, (int, float)) and hard_sec > 0:
        rules.append(Rule(
            name=f"{name}-hard",
            predicate=no_activity_for(float(hard_sec)),
            action=L5_KILL,
            reason="final hard backstop",
        ))
    return WatchdogPolicy(name=name, rules=rules)
