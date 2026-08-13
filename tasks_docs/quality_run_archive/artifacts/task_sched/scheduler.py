import threading
import time
from collections import deque


class Scheduler:
    def __init__(self):
        self._tasks = {}
        self._lock = threading.Lock()
        self.start_times = {}
        self.end_times = {}
        self.peak_active = 0

    def add(self, task_id, deps, fn):
        deps = list(deps)
        if not callable(fn):
            raise TypeError(f"fn must be callable for task {task_id!r}")
        if task_id in deps:
            raise ValueError(f"task {task_id!r} depends on itself: {[task_id]}")
        self._tasks[task_id] = {"deps": deps, "fn": fn}

    def _validate(self):
        tasks = self._tasks
        missing = sorted(
            dep
            for spec in tasks.values()
            for dep in spec["deps"]
            if dep not in tasks
        )
        if missing:
            raise KeyError(f"missing dependencies: {missing}")

        indeg = {
            tid: sum(1 for d in spec["deps"] if d in tasks)
            for tid, spec in tasks.items()
        }
        dependents = {tid: [] for tid in tasks}
        for tid, spec in tasks.items():
            for dep in spec["deps"]:
                if dep in tasks:
                    dependents[dep].append(tid)

        queue = deque(tid for tid, n in indeg.items() if n == 0)
        visited = 0
        while queue:
            u = queue.popleft()
            visited += 1
            for v in dependents[u]:
                indeg[v] -= 1
                if indeg[v] == 0:
                    queue.append(v)
        if visited != len(tasks):
            cyclers = sorted(tid for tid, n in indeg.items() if n > 0)
            raise ValueError(f"tasks form a cycle involving: {cyclers}")

    def run(self, max_parallel=4, stop_on_error=False):
        if max_parallel < 1:
            raise ValueError(f"max_parallel must be >= 1, got {max_parallel}")

        with self._lock:
            self._validate()
            tasks = self._tasks
            total = len(tasks)
            if total == 0:
                self.start_times = {}
                self.end_times = {}
                self.peak_active = 0
                return {}

            results = {}
            start_times = {}
            end_times = {}
            dependents = {tid: [] for tid in tasks}
            dep_count = {}
            for tid, spec in tasks.items():
                dep_count[tid] = len(spec["deps"])
                for dep in spec["deps"]:
                    dependents[dep].append(tid)

            ready = deque(tid for tid, n in dep_count.items() if n == 0)
            cv = threading.Condition(self._lock)
            active = 0
            completed = 0
            peak_active = 0
            stop = False
            first_error = None

        def worker():
            nonlocal active, completed, peak_active, stop, first_error
            while True:
                with cv:
                    while not (ready and not stop):
                        if stop:
                            if active == 0:
                                return
                            cv.wait()
                        elif completed == total:
                            return
                        else:
                            cv.wait()
                    tid = ready.popleft()
                    start_times[tid] = time.monotonic()
                    active += 1
                    peak_active = max(peak_active, active)
                    fn = tasks[tid]["fn"]
                try:
                    result = fn()
                except Exception as exc:
                    result = exc
                with cv:
                    end_times[tid] = time.monotonic()
                    active -= 1
                    completed += 1
                    results[tid] = result
                    if isinstance(result, Exception):
                        if stop_on_error and first_error is None:
                            first_error = result
                            stop = True
                    if not stop:
                        for d in dependents[tid]:
                            dep_count[d] -= 1
                            if dep_count[d] == 0:
                                ready.append(d)
                    cv.notify_all()

        threads = [
            threading.Thread(target=worker, daemon=True)
            for _ in range(min(max_parallel, total))
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.start_times = start_times
        self.end_times = end_times
        self.peak_active = peak_active
        if stop_on_error and first_error is not None:
            raise first_error
        return results
