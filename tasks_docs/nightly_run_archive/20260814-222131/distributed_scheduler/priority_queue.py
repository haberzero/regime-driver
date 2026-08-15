import heapq
import itertools
import threading
import time


class PriorityQueue:
    """Thread-safe priority queue with FIFO tie-breaking and aging.

    The scheduling key is ``(effective_priority, seq)``: a lower effective
    priority runs first, and the monotonic ``seq`` breaks ties in FIFO
    submission order. To prevent starvation, a job's effective priority
    improves (decreases) the longer it waits:

        effective_priority = priority - floor((now - enqueued_ts) / aging_interval)

    After ``aging_interval * (priority - min_priority + 1)`` seconds of
    waiting a job's effective priority is no worse than any newcomer, so
    every job is eventually dispatched. Each pop rebuilds the heap from the
    live entries, so both priority changes and aging are always reflected.
    """

    def __init__(self, aging_interval=5.0, clock=time.monotonic):
        if aging_interval is not None and aging_interval <= 0:
            raise ValueError("aging_interval must be positive or None")
        self._aging_interval = aging_interval
        self._clock = clock
        self._lock = threading.Lock()
        self._entries = {}
        self._counter = itertools.count()

    def push(self, job):
        with self._lock:
            if job.job_id in self._entries:
                return
            self._entries[job.job_id] = (job, self._clock(), next(self._counter))

    def update_priority(self, job):
        with self._lock:
            if job.job_id not in self._entries:
                return
            _, enqueued_ts, seq = self._entries[job.job_id]
            self._entries[job.job_id] = (job, enqueued_ts, seq)

    def remove(self, job_id):
        with self._lock:
            self._entries.pop(job_id, None)

    def pop(self):
        with self._lock:
            if not self._entries:
                return None
            now = self._clock()
            items = []
            for job_id, (job, enqueued_ts, seq) in self._entries.items():
                items.append((self._effective(job.priority, enqueued_ts, now), seq, job_id))
            heapq.heapify(items)
            _, _, job_id = heapq.heappop(items)
            return self._entries.pop(job_id)[0]

    def is_empty(self):
        with self._lock:
            return not self._entries

    def __len__(self):
        with self._lock:
            return len(self._entries)

    def _effective(self, priority, enqueued_ts, now):
        if self._aging_interval is None:
            return priority
        age = (now - enqueued_ts) // self._aging_interval
        return priority - int(age)
