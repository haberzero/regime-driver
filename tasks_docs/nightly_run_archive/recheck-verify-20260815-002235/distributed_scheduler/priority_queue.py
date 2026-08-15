import heapq
import threading
from dataclasses import dataclass

from clock import Clock


@dataclass
class _Entry:
    seq: int
    job_id: str
    priority: int
    enqueued_at: float
    removed: bool = False


class PriorityQueue:
    """Thread-safe priority queue: lowest priority first, FIFO on ties.

    Anti-starvation via age boosting: once a job has waited >= aging_threshold
    (measured on the injected clock), its effective priority is promoted above
    every not-yet-aged job; aged jobs are served FIFO by enqueued_at.

    Implemented with two heaps sharing the same _Entry objects:
      * _active: keyed (priority, seq)  -- ordering for non-aged jobs.
      * _time:   keyed (enqueued_at, seq) -- oldest job first for aged FIFO.
    Lazy removal: entries are flagged removed and skipped when they surface.
    """

    def __init__(self, aging_threshold: float = 5.0, clock: Clock = None):
        if aging_threshold is not None and (
            not isinstance(aging_threshold, (int, float)) or aging_threshold <= 0
        ):
            raise ValueError(f"aging_threshold must be a positive number or None, got {aging_threshold!r}")
        self._aging_threshold = aging_threshold
        self._clock = clock if clock is not None else Clock()
        self._lock = threading.Lock()
        self._active = []
        self._time = []
        self._entries = {}
        self._by_job = {}
        self._seq = 0
        self._live = 0

    @property
    def aging_threshold(self):
        return self._aging_threshold

    def _put_locked(self, priority: int, job_id: str, enqueued_at: float) -> int:
        self._seq += 1
        entry = _Entry(self._seq, job_id, priority, enqueued_at)
        self._entries[self._seq] = entry
        self._by_job[job_id] = self._seq
        heapq.heappush(self._active, (priority, self._seq))
        if self._aging_threshold is not None:
            heapq.heappush(self._time, (enqueued_at, self._seq))
        self._live += 1
        return self._seq

    def put(self, priority: int, job_id: str, enqueued_at: float = None) -> int:
        with self._lock:
            if enqueued_at is None:
                enqueued_at = self._clock()
            return self._put_locked(priority, job_id, enqueued_at)

    def _next_active_live(self):
        while self._active:
            _, seq = self._active[0]
            entry = self._entries.get(seq)
            if entry is None or entry.removed:
                heapq.heappop(self._active)
                continue
            return entry
        return None

    def _next_oldest_live(self):
        while self._time:
            _, seq = self._time[0]
            entry = self._entries.get(seq)
            if entry is None or entry.removed:
                heapq.heappop(self._time)
                continue
            return entry
        return None

    def pop(self):
        """Return (seq, job_id) of the next job, or None if empty."""
        with self._lock:
            now = self._clock()
            if self._aging_threshold is not None:
                oldest = self._next_oldest_live()
                if oldest is not None and now - oldest.enqueued_at >= self._aging_threshold:
                    heapq.heappop(self._time)
                    oldest.removed = True
                    self._by_job.pop(oldest.job_id, None)
                    self._live -= 1
                    return (oldest.seq, oldest.job_id)
            top = self._next_active_live()
            if top is None:
                return None
            heapq.heappop(self._active)
            top.removed = True
            self._by_job.pop(top.job_id, None)
            self._live -= 1
            return (top.seq, top.job_id)

    def peek(self):
        """Non-destructive version of pop (inspection only, O(n))."""
        with self._lock:
            now = self._clock()
            if self._aging_threshold is not None:
                best = None
                for _, seq in self._time:
                    entry = self._entries.get(seq)
                    if entry is not None and not entry.removed:
                        if best is None or (entry.enqueued_at, entry.seq) < (best.enqueued_at, best.seq):
                            best = entry
                if best is not None and now - best.enqueued_at >= self._aging_threshold:
                    return (best.seq, best.job_id)
            best = None
            for priority, seq in self._active:
                entry = self._entries.get(seq)
                if entry is not None and not entry.removed:
                    if best is None or (entry.priority, entry.seq) < (best.priority, best.seq):
                        best = entry
            if best is None:
                return None
            return (best.seq, best.job_id)

    def change_priority(self, job_id: str, new_priority: int) -> bool:
        """Change a queued job's priority; keeps its original enqueued_at."""
        with self._lock:
            seq = self._by_job.get(job_id)
            if seq is None:
                return False
            entry = self._entries.get(seq)
            if entry is None or entry.removed:
                return False
            if entry.priority == new_priority:
                return True
            entry.removed = True
            self._live -= 1
            self._put_locked(new_priority, job_id, entry.enqueued_at)
            return True

    def remove(self, job_id: str) -> bool:
        with self._lock:
            seq = self._by_job.get(job_id)
            if seq is None:
                return False
            entry = self._entries.get(seq)
            if entry is None or entry.removed:
                return False
            entry.removed = True
            self._by_job.pop(job_id, None)
            self._live -= 1
            return True

    def contains(self, job_id: str) -> bool:
        with self._lock:
            return job_id in self._by_job

    def __len__(self) -> int:
        with self._lock:
            return self._live
