from errors import InvalidPipelineError, StageFailure
from stages import Stage


class Pipeline:
    def __init__(self):
        self._stages = []
        self._deps = {}

    @property
    def stages(self):
        return tuple(self._stages)

    def add(self, stage, depends_on=None):
        if not isinstance(stage, Stage):
            raise TypeError(f"stage must be a Stage, got {type(stage).__name__}")
        if any(existing is stage for existing in self._stages):
            return self
        if stage.name is None:
            stage.name = f"stage_{len(self._stages) + 1}"
        if isinstance(depends_on, Stage):
            depends_on = depends_on.name
        if depends_on is not None:
            self._deps.setdefault(stage.name, set()).add(depends_on)
        self._stages.append(stage)
        return self

    def connect(self, upstream, downstream):
        u = upstream.name if isinstance(upstream, Stage) else upstream
        d = downstream.name if isinstance(downstream, Stage) else downstream
        self._deps.setdefault(d, set()).add(u)
        return self

    def validate(self):
        by_name = {}
        for stage in self._stages:
            if stage.name in by_name:
                raise InvalidPipelineError(f"duplicate stage name: {stage.name!r}")
            by_name[stage.name] = stage
        for name, deps in self._deps.items():
            if name not in by_name:
                continue
            for dep in deps:
                if dep not in by_name:
                    raise InvalidPipelineError(
                        f"invalid connection: stage {name!r} depends on unknown stage {dep!r}"
                    )
                if dep == name:
                    raise InvalidPipelineError(f"invalid connection: self-loop on stage {name!r}")
        WHITE, GRAY, BLACK = 0, 1, 2
        color = {name: WHITE for name in by_name}

        def dfs(node, path):
            color[node] = GRAY
            path.append(node)
            for nxt in sorted(self._deps.get(node, ())):
                if nxt not in by_name:
                    continue
                if color[nxt] == GRAY:
                    cycle = path[path.index(nxt):] + [nxt]
                    raise InvalidPipelineError(f"cycle detected: {' -> '.join(cycle)}")
                if color[nxt] == WHITE:
                    dfs(nxt, path)
            path.pop()
            color[node] = BLACK

        for node in by_name:
            if color[node] == WHITE:
                dfs(node, [])
        for i, stage in enumerate(self._stages):
            allowed = {self._stages[i - 1].name} if i > 0 else set()
            actual = self._deps.get(stage.name, set())
            if not actual <= allowed:
                raise InvalidPipelineError(
                    f"invalid connection: stage {stage.name!r} may only depend on its "
                    f"immediate predecessor {sorted(allowed) or 'none'}, got {sorted(actual)}"
                )
        return self

    def run(self, initial=None, fail_fast=False, batch_size=None):
        self.validate()
        if batch_size is not None and (not isinstance(batch_size, int) or batch_size <= 0):
            raise ValueError(f"batch_size must be a positive integer or None, got {batch_size!r}")
        input_rows = list(initial) if initial is not None else []
        if input_rows:
            batches = list(_chunk(input_rows, batch_size)) if batch_size else [input_rows]
        else:
            batches = []
        stats = {
            stage.name: {"in": 0, "out": 0, "failures": 0, "last_error": None}
            for stage in self._stages
        }
        failed = 0
        for batch in batches:
            rows = batch
            for stage in self._stages:
                entry = stats[stage.name]
                entry["in"] += len(rows)
                try:
                    rows = stage.run(rows)
                except Exception as exc:
                    entry["failures"] += 1
                    entry["last_error"] = f"{type(exc).__name__}: {exc}"
                    failed += len(rows)
                    if fail_fast:
                        raise StageFailure(
                            stage.name, f"stage {stage.name!r} failed (fail_fast)"
                        ) from exc
                    rows = []
                entry["out"] += len(rows)
        total = len(input_rows)
        return {
            "processed": total - failed,
            "failed": failed,
            "stage_stats": stats,
        }


def _chunk(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i:i + size]
