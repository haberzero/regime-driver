# Contributing

> **Status: in development.** The public API/CLI is not stable yet — expect
> breaking changes. If you'd like to contribute, coordinate with the maintainer
> first (open an issue/discussion before large PRs).

## Workflow

This repo follows a strict autonomous workflow (see `AGENTS.md` / `HANDOVER.md`):

- **Code review**: done by a read-only reviewer agent. The project does **not**
  use the `reviewer` subagent; reviews are run via the `general` agent.
- **No push by default**: only local commits unless explicitly authorized.
- **Quality gates**: every task must pass the full test suite with zero
  regressions before being marked done / committed.

## Setup

```bash
conda create -n regime-driver python=3.12
conda run -n regime-driver pip install -e ".[dev]"
conda run -n regime-driver python -m pytest      # 333+ tests
```

## Conventions

- Pure domain logic lives in `core/`; file/network I/O in `infra/`; state-machine
  units in `app/`.
- New public API must have a production consumer (see `tests/test_deadcode.py`).
- Keys never committed; use `~/.regime/keys/*.key` or env vars.
- Documentation follows `docs/WRITING_GUIDE.md` + `workflow-regime/skills/doc-governance/SKILL.md`.

## Testing

```bash
# offline unit tests (no worker, no key)
conda run -n regime-driver python -m pytest
# coverage gate
conda run -n regime-driver python -m pytest --cov=regime_driver --cov-fail-under=68
# real-worker E2E (requires a live worker + model key)
REGIME_E2E=1 conda run -n regime-driver python -m pytest tests/test_e2e_worker.py -q
```

See `HANDOVER.md §9` for the full command reference.
