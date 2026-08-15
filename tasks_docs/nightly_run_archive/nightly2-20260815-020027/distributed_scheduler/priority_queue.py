import heapq
import threading
import time
from typing import Dict, Optional


class PriorityQueue:
    """Thread-safe priority queue: lower priority value wins, FIFO breaks ties.

    Entries are heap tuples (effective_priority, seq, job_id, version). Lazy
    deletion is used: cancelling or changing a job bumps its version and pushes
    a fresh entry; stale entries are skipped on pop.

    Anti-starvation aging: a queued job's effective priority improves by
    ``aging_step`` for every ``aging_interval`` seconds it has been waiting:
    ``effective = priority - floor(wait / aging_interval) * aging_step``.
    This guarantees any queued job eventually reaches the head of the queue.
    """

    def __init__(self, aging_interval: float = 5.0, aging_step: int = 1, now_fn=time.time):
        if aging_interval <= 0:
            raise ValueError("aging_interval must be > 0")
        if aging_step < 1:
            raise ValueError("aging_step must be >= 1")
        self._cond = threading.Condition()
        self._heap = []
        self._tracked: Dict[str, dict] = {}
        self._seq = 0
        self._closed = False
        self._aging_interval = aging_interval
        self._aging_step = aging_step
        self._now_fn = now_fn

    def _wait_seconds(self, entry: dict) -> int:
        wait = self._now_fn() - entry["enqueue_ts"]
        if wait < 0:
            return 0
        return int(wait // self._aging_interval)

    def _boosts(self, entry: dict) -> int:
        return self._wait_seconds(entry) * self._aging_step

    def _materialize(self) -> None:
        now = self._now_fn()
        for job_id, entry in self._tracked.items():
            wait = now - entry["enqueue_ts"]
            if wait < 0:
                wait = 0
            boosts = int(wait // self._aging_interval) * self._aging_step
            if boosts != entry["boosted"]:
                entry["boosted"] = boosts
                entry["version"] += 1
                heapq.heappush(
                    self._heap,
                    (entry["priority"] - boosts, entry["seq"], job_id, entry["version"]),
                )

    def push(self, job_id: str, priority: int) -> bool:
        with self._cond:
            if self._closed:
                return False
            entry = {
                "priority": priority,
                "seq": self._seq,
                "enqueue_ts": self._now_fn(),
                "boosted": 0,
                "version": 0,
            }
            self._seq += 1
            self._tracked[job_id] = entry
            heapq.heappush(self._heap, (priority, entry["seq"], job_id, 0))
            self._cond.notify()
            return True

    def pop(self, block: bool = True, timeout: Optional[float] = None) -> Optional[str]:
        deadline = None if timeout is None else self._now_fn() + timeout
        with self._cond:
            while True:
                if self._closed:
                    return None
                self._materialize()
                while self._heap:
                    eff, seq, job_id, version = heapq.heappop(self._heap)
                    entry = self._tracked.get(job_id)
                    if entry is None or entry["version"] != version:
                        continue
                    current_eff = entry["priority"] - self._boosts(entry)
                    if current_eff != eff:
                        heapq.heappush(self._heap, (current_eff, seq, job_id, version))
                        continue
                    del self._tracked[job_id]
                    return job_id
                if not block:
                    return None
                if deadline is not None:
                    remaining = deadline - self._now_fn()
                    if remaining <= 0:
                        return None
                    self._cond.wait(remaining)
                else:
                    self._cond.wait()

    def change_priority(self, job_id: str, new_priority: int) -> bool:
        with self._cond:
            entry = self._tracked.get(job_id)
            if entry is None:
                return False
            entry["priority"] = new_priority
            entry["version"] += 1
            heapq.heappush(
                self._heap,
                (new_priority - entry["boosted"], entry["seq"], job_id, entry["version"]),
            )
            self._cond.notify()
            return True

    def remove(self, job_id: str) -> bool:
        with self._cond:
            if job_id in self._tracked:
                del self._tracked[job_id]
                return True
            return False

    def contains(self, job_id: str) -> bool:
        with self._cond:
            return job_id in self._tracked

    def qsize(self) -> int:
        with self._cond:
            return len(self._tracked)

    def clear(self) -> None:
        with self._cond:
            self._heap.clear()
            self._tracked.clear()
            self._seq = 0

    def close(self) -> None:
        with self._cond:
            self._closed = True
            self._cond.notify_all()

    def notify_all(self) -> None:
        with self._cond:
            self._cond.notify_all()
