"""Thread-safe priority queue with FIFO tie-break and anti-starvation age boost.

Heap entries are ``(effective_priority, seq, job_id)``. ``seq`` is a
monotonic counter assigned on first enqueue and preserved across priority
updates, giving FIFO ordering among equal effective priorities. Priority
updates mark the old entry removed and push a new entry with the same
``seq``. The age boost is computed lazily at pop time with the injected
clock:

    boost = boost_step * floor(waiting_seconds / boost_interval)
    effective_priority = priority - boost

The boost is unbounded by default, which guarantees any job is eventually
popped even while higher-priority jobs keep arriving: a job at priority ``p``
is served within ``ceil((p - q_min) / boost_step) * boost_interval`` seconds,
where ``q_min`` is the minimum priority ever enqueued. When a popped entry's
recomputed effective priority differs from its stored key, the entry is
re-pushed with the new key and the loop retries.
"""

import heapq
import itertools
import threading
import time


class PriorityQueue:
    def __init__(self, clock=None, boost_interval=1.0, boost_step=1, max_boost=None):
        self._clock = clock or time.time
        self._interval = boost_interval
        self._step = boost_step
        self._max_boost = max_boost
        self._cond = threading.Condition()
        self._heap = []
        self._entries = {}
        self._seq = itertools.count()

    def _effective(self, entry):
        waited = max(0.0, self._clock() - entry["entered_at"])
        if self._interval > 0:
            boost = int(waited // self._interval) * self._step
        else:
            boost = 0
        if self._max_boost is not None:
            boost = min(boost, self._max_boost)
        return entry["prio"] - boost

    def _push(self, entry, job_id):
        seq = next(self._seq)
        entry["seq"] = seq
        heapq.heappush(self._heap, (self._effective(entry), seq, job_id))
        self._cond.notify_all()

    def put(self, job_id, priority, now=None):
        with self._cond:
            now = self._clock() if now is None else now
            current = self._entries.get(job_id)
            if current is not None and not current["removed"]:
                current["removed"] = True
            entry = {"prio": priority, "entered_at": now, "removed": False, "seq": 0}
            self._entries[job_id] = entry
            self._push(entry, job_id)

    def update_priority(self, job_id, priority):
        with self._cond:
            current = self._entries.get(job_id)
            if current is None or current["removed"]:
                return False
            current["removed"] = True
            entry = {
                "prio": priority,
                "entered_at": current["entered_at"],
                "removed": False,
                "seq": current["seq"],
            }
            self._entries[job_id] = entry
            heapq.heappush(self._heap, (self._effective(entry), entry["seq"], job_id))
            self._cond.notify_all()
            return True

    def pop(self, stop=None):
        with self._cond:
            while True:
                if stop is not None and stop.is_set():
                    return None
                if self._interval > 0 and self._heap:
                    self._rebuild()
                while self._heap:
                    eff, seq, job_id = self._heap[0]
                    entry = self._entries.get(job_id)
                    if entry is None or entry["removed"] or entry["seq"] != seq:
                        heapq.heappop(self._heap)
                        continue
                    heapq.heappop(self._heap)
                    del self._entries[job_id]
                    return job_id
                self._cond.wait(0.05)

    def _rebuild(self):
        """Refresh every live entry's effective priority for the current clock.

        Age boost lowers a buried entry's effective priority over time, so
        keys can go stale between interval boundaries. Rebuilding keeps the
        heap exact, which costs O(n) per pop but guarantees we always pop the
        true minimum (and thus the hard anti-starvation bound).
        """
        rebuilt = [
            (self._effective(entry), entry["seq"], job_id)
            for job_id, entry in self._entries.items()
            if not entry["removed"]
        ]
        self._heap = rebuilt
        heapq.heapify(self._heap)

    def remove(self, job_id):
        with self._cond:
            entry = self._entries.get(job_id)
            if entry is not None:
                entry["removed"] = True

    def __len__(self):
        with self._cond:
            return sum(1 for e in self._entries.values() if not e["removed"])
