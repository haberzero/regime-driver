from errors import InvalidPipelineError, StageFailure
from stages import Stage


class Pipeline:
    """Sequential ETL pipeline with graph validation and batch isolation."""

    def __init__(self):
        self._stages = []
        self._by_name = {}
        self._edges = []

    @property
    def stages(self):
        return list(self._stages)

    @property
    def stage_names(self):
        return [stage.name for stage in self._stages]

    def add(self, stage):
        """Add a stage; idempotent for the same object, auto-names unnamed stages."""
        if not isinstance(stage, Stage):
            raise TypeError(f"expected a Stage, got {type(stage).__name__}")
        for existing in self._stages:
            if existing is stage:
                return self
        name = stage.name
        if name is None:
            name = f"stage_{len(self._stages)}"
            stage.name = name
        elif name in self._by_name:
            raise InvalidPipelineError([f"duplicate stage name: {name!r}"])
        self._stages.append(stage)
        self._by_name[name] = stage
        return self

    def _resolve(self, stage_or_name):
        if isinstance(stage_or_name, Stage):
            if stage_or_name not in self._stages:
                raise InvalidPipelineError([f"stage not in pipeline: {stage_or_name.name!r}"])
            return stage_or_name.name
        if stage_or_name in self._by_name:
            return stage_or_name
        raise InvalidPipelineError([f"unknown stage: {stage_or_name!r}"])

    def connect(self, from_stage, to_stage):
        """Declare an explicit edge for validation; run() still executes in add order."""
        src = self._resolve(from_stage)
        dst = self._resolve(to_stage)
        if src == dst:
            raise InvalidPipelineError([f"self-loop on stage {src!r}"])
        if (src, dst) in self._edges:
            raise InvalidPipelineError([f"duplicate edge: {src} -> {dst}"])
        self._edges.append((src, dst))
        return self

    def validate(self):
        """Check duplicate names, illegal edges, and cycles; raise InvalidPipelineError."""
        problems = []

        seen = set()
        for stage in self._stages:
            if stage.name in seen:
                problems.append(f"duplicate stage name: {stage.name!r}")
            seen.add(stage.name)

        for src, dst in self._edges:
            if src not in self._by_name or dst not in self._by_name:
                problems.append(f"illegal connection: {src} -> {dst}")

        graph = {}
        for index in range(len(self._stages) - 1):
            src = self._stages[index].name
            dst = self._stages[index + 1].name
            graph.setdefault(src, set()).add(dst)
        for src, dst in self._edges:
            graph.setdefault(src, set()).add(dst)

        cycle = self._find_cycle(graph)
        if cycle:
            problems.append("cycle detected: " + " -> ".join(cycle))

        if problems:
            raise InvalidPipelineError(problems, cycle=cycle)
        return self

    @staticmethod
    def _find_cycle(graph):
        visited = set()
        path = []

        def dfs(node):
            visited.add(node)
            path.append(node)
            for nxt in graph.get(node, ()):
                if nxt in path:
                    return path[path.index(nxt):] + [nxt]
                if nxt not in visited:
                    found = dfs(nxt)
                    if found:
                        return found
            path.pop()
            return None

        for node in list(graph):
            if node not in visited:
                found = dfs(node)
                if found:
                    return found
        return None

    def run(self, initial=None, batch_size=None, fail_fast=False):
        """Execute stages in order; isolate failed batches unless fail_fast."""
        self.validate()
        if batch_size is not None and batch_size <= 0:
            raise ValueError("batch_size must be > 0")

        rows = list(initial or [])
        if not rows:
            return {
                "processed": 0,
                "failed": 0,
                "stage_stats": {
                    stage.name: {"in": 0, "out": 0, "failed": 0}
                    for stage in self._stages
                },
                "failures": [],
            }
        if batch_size is None:
            batch_size = len(rows)
        batches = [rows[index:index + batch_size] for index in range(0, len(rows), batch_size)]

        stage_stats = {
            stage.name: {"in": 0, "out": 0, "failed": 0}
            for stage in self._stages
        }
        failures = []
        processed = 0
        failed = 0

        for batch in batches:
            current = batch
            batch_failed = False
            for stage in self._stages:
                stage_stats[stage.name]["in"] += len(current)
                try:
                    current = stage.run(current)
                except Exception as exc:
                    stage_stats[stage.name]["failed"] += 1
                    failures.append({"stage": stage.name, "batch": batch, "error": exc})
                    failed += 1
                    if fail_fast:
                        raise StageFailure(stage, batch, exc) from exc
                    batch_failed = True
                    break
                stage_stats[stage.name]["out"] += len(current)
            if not batch_failed:
                processed += len(batch)

        return {
            "processed": processed,
            "failed": failed,
            "stage_stats": stage_stats,
            "failures": failures,
        }
