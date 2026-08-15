from typing import Any, Dict, List


class Recovery:
    """Crash recovery: replay the WAL into a fresh scheduler instance.

    Jobs whose RUNNING state has no terminal event are marked back to QUEUED so
    they get rescheduled. The idempotency registry is rebuilt so completed
    idempotent jobs are never re-executed and duplicate keys are still rejected.
    """

    @staticmethod
    def recover(store, queue, registry, metrics, now_fn) -> Dict[str, Any]:
        jobs: List[Any] = store.replay()
        recovered_ids: List[str] = []
        for job in jobs:
            if job.state == "RUNNING":
                job.state = "QUEUED"
                recovered_ids.append(job.job_id)
                metrics.inc("recovered")
            if job.state == "QUEUED":
                if job.deadline is not None and now_fn() > job.deadline:
                    job.state = "FAILED"
                    job.timed_out = True
                    job.error = "deadline passed while the process was down"
                    metrics.inc("deadline_hit")
        registry.reset()
        for job in jobs:
            if job.idempotency_key:
                registry.register(job.idempotency_key, job.job_id)
        for job in jobs:
            if job.state == "QUEUED":
                queue.push(job.job_id, job.priority)
        return {"jobs": jobs, "recovered_ids": recovered_ids}
