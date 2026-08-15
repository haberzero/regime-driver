# regime-driver

> **⚠️ Experimental · In Development — currently v0.1.**
> No stable API/CLI contract. Interfaces and behaviour may change
> without notice. Long-running durability (2h+ no-leak/recovery) is being
> systematically validated; real-model E2E is available locally only;
> some machine/model/path/port defaults are project-specific. **Use at your own
> risk** — it drives real AI models and Docker containers and can auto-execute
> code. Run it only in a controlled, isolated environment. See `SECURITY.md`.

Read this in [中文](./README.md).

---

Turns the "meta-instructions" you give opencode into **deterministic flows that
are always executed**. regime-driver compiles a workflow (an ordered set of
role-aware steps: understand → design → implement → review → wrap) into a
**state machine** and drives a clean, plugin-free opencode worker node by node:

- **Work and review are separated**: work nodes run on a developer session,
  review nodes are judged by a read-only reviewer.
- **A deterministic gate guards each step**: a review that fails the gate does
  **not** advance.
- **Out-of-process supervision**: an independent clock watches for stalls,
  freezes and timeouts, and escalates through a correction ladder.
- **Everything is replayable**: every run is written to an event ledger and a
  report journal.

**An operating rule (Regime) is a first-class object**: bundle *how a task runs*
(flow + role policies + supervision watchdog + context handover) into one
named, registerable, hot-reloadable **Regime** —
`regime regime design <name> '<JSON>'` registers it, `regime run/drive --regime-name <name>`
runs the whole rule. Companions: `~/.regime/hooks.py` unified extension points
(lifecycle hooks + watchdog rules + custom tools), reviewer-requested **human
confirmation points** (`decide <workflow> <yes|no>` in the dialog), and judge
nodes can declare `verify` to run real tests before judging (whitelisted,
RCE-free).

**Core architecture**: a peer state-machine network — a "watchdog"
(intelligent-free state machines + a signal protocol + runtime-enforced root
invariants) supervising agentic workflow units. See
`docs/architecture/02_statechart_network.md`.

## Status / highlights

- **Tests**: full `python -m pytest` green (coverage per current run); real-worker
  E2E available locally via `REGIME_E2E=1`.
- **CI is green**: unit tests pass on Python 3.11 & 3.12 (offline, no key needed).
- Core features implemented & verified: hot flow compile/reload
  (`FlowRegistry` + `regime flow`), one-command self-driving stack (`regime drive`),
  per-workspace isolated worker batch (`regime worker` / `drive-many`),
  fault-injection/recovery (`regime chaos`), web console (`regime web`),
  supervised task registry (`regime task` / `regime job logs`), Dialog Control
  (A/B dual surface), workspace-mode install (`scaffold/setup/uninstall
  --workspace`, `doctor --workspace`).
- External-supply readiness (templates in wheel / `regime scaffold` / single
  source of truth / release docs) and long-run durability (2h+ real run) are
  complete.

## Install

```bash
conda create -n regime-driver python=3.12
conda run -n regime-driver pip install -e ".[dev]"
```

> The pip wheel ships the official templates (agents/skills/dialog-control plugin and
> agent, opencode config), so you can `regime scaffold` a full config without cloning
> the repo. Docker build assets live in the GitHub repo, not the wheel.

## Deployment

### 1. Fetch official templates (once)

```bash
# recommended: workspace mode — deploy into <dir>/.opencode/ (agent, skills,
# plugin, agent-handbook); does not pollute other projects (idempotent;
# --dry-run previews without writing)
regime setup --workspace <your-project-dir>
regime setup --workspace <dir> --assistants   # also deploy analyst/advisor/reviewer
# global mode (NOT recommended: tools become visible to every opencode project;
# see docs/architecture/04_distribution_blueprint.md)
regime scaffold [--assistants]
# self-check: worker health / model key / templates ready
regime doctor
```

### 2. Bring up the execution surface

**Containerized (recommended)** — build + start worker/dialog-control containers and wait for health:

```bash
ops/up.sh all            # worker + dialog-control
ops/up.sh dialog-control --rebuild  # force-rebuild the pinned image
```

> `ops/up.sh` lives in the source repo (not shipped in the wheel). Wheel-only
> users use **host mode** below (opencode as the primary dialog + worker); for
> containers, clone the repo (Dockerfiles live in the repo `docker/`, not in the
> wheel). See `docs/architecture/04_distribution_blueprint.md`.

**Host mode** — drive an opencode service running on the host directly:

```bash
regime run "task" --base http://<host-opencode-port>
```

### 3. Configure the model key

- worker/dialog-control containers receive `DEEPSEEK_API_KEY` at runtime (`ops/up.sh` reads
  `~/.regime/keys/deepseek.key` or your env); keys are never committed. The
  OpenCode Go fallback provider uses `OPENCODE_GO_API_KEY`.
- Interactive opencode stores keys via `/connect` in
  `~/.local/share/opencode/auth.json`.
- See `docs/guide/04_environment.md`.

## Quick start

```bash
# validate / run one task / run concurrent tasks / gate a verdict / health / sessions
regime validate
regime run "implement add(x,y) and write pytest" --base http://127.0.0.1:4097
regime run-many "add(x,y)" "mul(x,y)" --base http://127.0.0.1:4097
regime gate '{"node":"design","verdict":"advance","action":"advance","next_state":"implement","confidence":0.9,"reason":"ok"}'
regime status --base http://127.0.0.1:4097
regime sessions [--clean|--kill <id>] --base http://127.0.0.1:4097

# hot flow lifecycle (single source of truth for named flows)
regime flow list | validate <file> [--watch] | load <file> | reload <name> | rm <name> | inspect <name>

# self-driving stack & parallel batch
regime drive "task" --base http://127.0.0.1:4097 --container opencode-worker
regime drive-many "t1" "t2" --workspaces "wsA,wsB"

# Dialog Control (single conversational control surface)
regime dialog --live --base http://127.0.0.1:4097
```

## Tests

```bash
conda run -n regime-driver python -m pytest            # full suite, no worker needed
conda run -n regime-driver python -m pytest --cov=regime_driver --cov-fail-under=68
REGIME_E2E=1 conda run -n regime-driver python -m pytest e2e_tests/test_e2e_worker.py -q  # real worker
```

## Configuration & secrets

- Config file: `config.example.toml` (all fields documented). Priority:
  default < config file < env (`REGIME_<FIELD>`) < CLI args.
- **Model API keys are never committed.** Provide `DEEPSEEK_API_KEY` env (the
  default `deepseek-api/deepseek-v4-flash` provider), or write
  `~/.regime/keys/<name>.key`; containers receive them only at runtime. The
  `my-opencode-go/...` (OpenCode Go) provider is the fallback. Self-check:
  `regime doctor` (reports key presence only, never the value).

## Documentation

- Documentation site (MkDocs + Read the Docs theme):
  `https://haberzero.github.io/regime-driver/` — start at the portal home
  (what/why/features/what-you-can-do), organized by reader: **User Guide**
  (run/configure/operate), **Reference** (CLI/config/flow spec), **Developer
  Guide** (architecture/subsystems/how-to-develop).
- In-repo navigation: `docs/README.md`. Known limits: `docs/KNOWN_LIMITS.md`.
  Writing standards: `docs/WRITING_GUIDE.md`.
- Task-control docs (historical): `tasks_docs/` (WORKLOG / MAIN_TASKS / PENDING_TASKS).
- Note: `docs-ref/` is a reference copy of another project's docs — it is **not
  committed** (gitignored), kept only as writing guidance. Agent-only internals
  (skills / dialog-control assistants / workflow-regime templates) stay machine-specific
  and are not part of the docs site.

## License & disclaimer

- **MIT License** (© 2026 Nan Shi 施楠). See `LICENSE`.
- **In development, provided AS-IS with no warranty of any kind.** It drives
  real AI models and Docker, and can auto-execute code — audit its behaviour and
  run it in an isolated sandbox. See `SECURITY.md`.
