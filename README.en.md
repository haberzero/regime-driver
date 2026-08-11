# regime-driver

> **⚠️ Experimental · In Development — NOT yet released.**
> No stable API/CLI contract, no `v1.0`. Interfaces and behaviour may change
> without notice. Long-running durability (2h+ no-leak/recovery) is not yet
> systematically validated; CI is now green but real-model E2E is key-gated;
> some machine/model/path/port defaults are project-specific. **Use at your own
> risk** — it drives real AI models and Docker containers and can auto-execute
> code. Run it only in a controlled, isolated environment. See `SECURITY.md`.

Read this in [中文](./README.md).

---

An L1 institutional-process robot (OA system). It compiles an institutional
workflow (`workflow-regime/`) into a **state machine** and drives a clean,
plugin-free `opencode` worker (L2) to complete tasks, with a read-only reviewer
(L0) judging and a deterministic gate guarding each step.

**Final architecture**: a peer state-machine network — a "constitution"
(intelligent-free state machines + a signal protocol + runtime-enforced root
invariants) supervising agentic workflow units. See
`docs/architecture/02_statechart_network.md`.

## Status / highlights

- **Tests**: full `python -m pytest` green (71%+ coverage, incl. real-worker E2E,
  gated behind `REGIME_E2E`).
- **Real CI is green**: unit tests pass on Python 3.11 & 3.12; real-worker E2E
  activates when an `OPENCODE_GO_API_KEY` secret is set.
- Core features implemented & verified: hot flow compile/reload
  (`FlowRegistry` + `regime flow`), one-command self-driving stack (`regime drive`),
  per-workspace isolated worker fleet (`regime worker` / `drive-many`),
  fault-injection/recovery (`regime chaos`), God Dialog (A/B dual surface).
- External-supply readiness (templates in wheel / `regime scaffold` / single
  source of truth / release docs) tracked in `WORK_PLAN7.md`.

## Install

```bash
conda create -n regime-driver python=3.12
conda run -n regime-driver pip install -e ".[dev]"
```

> The pip wheel ships the official templates (agents/skills/god-assistants/docker
> recipes), so you can `regime scaffold` a full config without cloning the repo.

## Deployment

### 1. Fetch official templates (once)

```bash
# generate ~/.config/opencode/{agents,skills} from the packaged templates
# (idempotent; --dry-run previews without writing)
regime scaffold
# also deploy the god-dialog assistant subagents (analyst/advisor)
regime scaffold --god
# self-check: worker health / model key / templates ready
regime doctor
```

### 2. Bring up the execution surface

**Containerized (recommended)** — build + start worker/god containers and wait for health:

```bash
ops/up.sh all            # worker + god
ops/up.sh god --rebuild  # force-rebuild the pinned image
```

**Host mode** — drive an opencode service running on the host directly:

```bash
regime run "task" --base http://<host-opencode-port>
```

### 3. Configure the model key

- worker/god containers receive `OPENCODE_GO_API_KEY` / `DEEPSEEK_API_KEY` at
  runtime (`ops/up.sh` reads `~/.regime/keys/*.key` or your env); keys are never
  committed.
- Interactive opencode stores keys via `/connect` in
  `~/.local/share/opencode/auth.json`.
- See `docs/guide/00_environment.md`.

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

# self-driving stack & fleet
regime drive "task" --base http://127.0.0.1:4097 --container opencode-worker
regime drive-many "t1" "t2" --workspaces "wsA,wsB"

# God Dialog (single conversational control surface)
regime dialog --live --base http://127.0.0.1:4097
```

## Tests

```bash
conda run -n regime-driver python -m pytest            # full suite, no worker needed
conda run -n regime-driver python -m pytest --cov=regime_driver --cov-fail-under=68
REGIME_E2E=1 conda run -n regime-driver python -m pytest tests/test_e2e_worker.py -q  # real worker
```

## Configuration & secrets

- Config file: `config.example.toml` (all fields documented). Priority:
  default < config file < env (`REGIME_<FIELD>`) < CLI args.
- **Model API keys are never committed.** Provide `OPENCODE_GO_API_KEY` /
  `DEEPSEEK_API_KEY` env, or write `~/.regime/keys/<name>.key`; containers receive
  them only at runtime. Default model is `deepseek-api/deepseek-v4-flash` (official DeepSeek API)
  (OpenCode Go) with `deepseek-api/...` as fallback. Self-check: `regime doctor`
  (reports key presence only, never the value).

## Documentation

- Navigation & reading order: `docs/README.md`. Design/usability:
  `docs/guide/00_environment.md`. God Dialog operator manual:
  `docs/reference/05_god_dialog_contract.md`. Known limits: `docs/KNOWN_LIMITS.md`.
- Work plans: `WORK_PLAN.md`–`WORK_PLAN7.md` (current main line: external-supply
  readiness, `WORK_PLAN7.md`).
- Note: `docs-ref/` is a reference copy of another project's docs — it is **not
  committed** (gitignored), kept only as writing guidance.

## License & disclaimer

- **MIT License** (© 2026 Nan Shi 施楠). See `LICENSE`.
- **In development, provided AS-IS with no warranty of any kind.** It drives
  real AI models and Docker, and can auto-execute code — audit its behaviour and
  run it in an isolated sandbox. See `SECURITY.md`.
