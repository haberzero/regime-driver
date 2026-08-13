"""Pipeline orchestration: graph validation, sequential execution, isolation.

Stages run in the order they were added. Connections between stages (explicit
``depends_on`` or later ``connect`` edges) are validated but execution itself
is sequential — the output of each stage feeds the next one.
"""

from errors import InvalidPipelineError, StageFailure
from stages import Stage


class Pipeline:
    """A validated, sequentially-executed graph of stages.

    ``add`` auto-names unnamed stages ``stage_<n>`` by insertion order
    (idempotent: existing names are never rewritten). ``validate`` checks for
    duplicate stage names, dangling connections, and cycles. ``run`` executes
    the stages in order; by default a failing batch is isolated (recorded as
    failed for that stage, later stages still run), unless ``fail_fast=True``
    is given, in which case a :class:`errors.StageFailure` is raised.
    """

    def __init__(self):
        self._stages = []
        self._deps = {}

    @property
    def stages(self):
        return list(self._stages)

    def add(self, stage, depends_on=None):
        """Append ``stage``, auto-naming it if unnamed. Returns ``self``."""
        if not isinstance(stage, Stage):
            raise TypeError("stage must be a Stage instance")
        if not stage.name:
            stage.name = "stage_%d" % (len(self._stages) + 1)
        if isinstance(depends_on, str):
            deps = {depends_on}
        else:
            deps = set(depends_on or ())
        if not deps and self._stages:
            deps = {self._stages[-1].name}
        self._deps[stage.name] = deps
        self._stages.append(stage)
        return self

    def connect(self, downstream, upstream):
        """Add an edge so ``downstream`` runs after ``upstream``. Returns ``self``."""
        if downstream not in self._deps:
            raise InvalidPipelineError("unknown stage %r" % downstream)
        self._deps[downstream].add(upstream)
        return self

    def validate(self):
        """Detect duplicate names, dangling connections, and cycles.

        Raises :class:`errors.InvalidPipelineError` with a message naming the
        offending stage(s) or the cycle path (shallow graph check).
        """
        names = [s.name for s in self._stages]
        seen, dups = set(), []
        for name in names:
            if name in seen and name not in dups:
                dups.append(name)
            seen.add(name)
        if dups:
            raise InvalidPipelineError(
                "duplicate stage name(s): %s" % ", ".join(dups)
            )

        unknown = sorted(
            dep
            for deps in self._deps.values()
            for dep in deps
            if dep not in self._deps
        )
        if unknown:
            raise InvalidPipelineError(
                "invalid connection(s) to unknown stage(s): %s"
                % ", ".join(unknown)
            )

        visiting, visited = set(), set()

        def visit(node, path):
            if node in visiting:
                start = path.index(node)
                cycle = path[start:] + [node]
                raise InvalidPipelineError(
                    "cycle detected: %s" % " -> ".join(cycle)
                )
            if node in visited:
                return
            visiting.add(node)
            for dep in sorted(self._deps.get(node, ())):
                visit(dep, path + [node])
            visiting.discard(node)
            visited.add(node)

        for node in self._deps:
            visit(node, [])
        return True

    def run(self, initial=None, fail_fast=False):
        """Execute the pipeline and return ``{processed, failed, stage_stats}``.

        ``processed``/``failed`` are summed across per-stage stats: a stage
        counts ``len(rows)`` as processed when it returns successfully and as
        failed when its run raises.
        """
        self.validate()
        rows = list(initial) if initial is not None else []
        stage_stats = {}
        for stage in self._stages:
            stat = {"processed": 0, "failed": 0}
            stage_stats[stage.name] = stat
            try:
                out = list(stage.run(rows))
            except Exception as exc:
                stat["failed"] = len(rows)
                if fail_fast:
                    raise StageFailure(stage.name, exc) from exc
                rows = []
                continue
            stat["processed"] = len(rows)
            rows = out

        return {
            "processed": sum(s["processed"] for s in stage_stats.values()),
            "failed": sum(s["failed"] for s in stage_stats.values()),
            "stage_stats": stage_stats,
        }
