import time

NOOP_SLEEP = lambda _: None  # noqa: E731


def wait_status(scheduler, job_id, expected, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if scheduler.status(job_id) == expected:
            return
        time.sleep(0.01)
    raise AssertionError(
        f"job {job_id!r} did not reach {expected!r}; got {scheduler.status(job_id)!r}"
    )
