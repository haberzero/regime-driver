# regime-driver

L1 institutional-process robot (OA system). Compiles the `workflow-regime`
institutional process into a state machine and drives a clean opencode worker
(L2) to complete work, advancing through reviewer (L0) judgements gated by a
deterministic gate.

See `docs/ARCHITECTURE-regime-driver.md` for the full architecture.

## Install

```bash
pip install -e .
```

## Usage

```bash
regime validate --regime ops/regime/regime.json
regime run "task context" --base http://127.0.0.1:4097
regime gate '{"node":"p2","verdict":"advance","action":"advance","next_state":"p3","confidence":0.8,"reason":"ok"}'
regime status --base http://127.0.0.1:4097
```

## Development

```bash
conda create -n regime-driver python=3.12
conda run -n regime-driver pip install -e ".[dev]"
conda run -n regime-driver pytest
```