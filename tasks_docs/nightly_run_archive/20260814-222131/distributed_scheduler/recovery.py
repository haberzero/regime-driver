def recover(store):
    """Reconstruct all job state from the store and reschedule interrupted work.

    WAL replay restores every committed job. Jobs that were executing when
    the log ended are rolled back to ``queued`` so they are re-dispatched;
    jobs that reached a terminal state (including completed idempotent jobs)
    are preserved exactly and never re-run.

    Returns a ``(rolled, queued)`` tuple where ``rolled`` is the list of job
    ids that were running (now queued again) and ``queued`` is the list of
    JobRecords in ``queued`` state ready for dispatch.
    """
    running = store.recover()
    for job_id in running:
        store.mark_queued(job_id)
    queued = [record for record in store.all_jobs().values() if record.state == "queued"]
    return list(running), queued
