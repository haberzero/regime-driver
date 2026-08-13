"""Crash recovery: replay the WAL and reschedule interrupted jobs.

Recovery rebuilds all committed jobs from the log (full replay, optionally
seeded by a snapshot checkpoint), marks any job that was executing at crash
time back to ``queued`` so it is rescheduled, re-attaches callables supplied
by the caller, and re-enqueues every runnable queued job into the priority
queue. Jobs already in a terminal state -- in particular ``succeeded``
idempotent jobs -- are never re-executed.
"""

from job_store import QUEUED, RUNNING


class Recovery:
    def __init__(self, store, priority_queue, metrics, clock=None):
        self._store = store
        self._pq = priority_queue
        self._metrics = metrics

    def apply(self, fn_provider=None):
        recovered = 0
        for job in self._store.all():
            if job.state == RUNNING:
                self._store.mark_recovered(job.job_id)
                self._metrics.inc("recovered")
                recovered += 1
        for job in self._store.all():
            if job.fn is None and job.state == QUEUED:
                job.fn = self._resolve_fn(fn_provider, job)
        for job in self._store.all():
            if job.state == QUEUED and job.fn is not None:
                self._pq.put(job.job_id, job.priority)
        return recovered

    @staticmethod
    def _resolve_fn(provider, job):
        if provider is None:
            return None
        if callable(provider):
            return provider(job)
        if job.job_id in provider:
            return provider[job.job_id]
        if job.idempotency_key and job.idempotency_key in provider:
            return provider[job.idempotency_key]
        return None
