import pytest


@pytest.fixture
def make_scheduler(tmp_path):
    created = []

    def _make(**kwargs):
        from api import Scheduler

        defaults = dict(worker_count=2, backoff_base=0.001, backoff_max=0.01)
        defaults.update(kwargs)
        s = Scheduler(wal_path=str(tmp_path / "wal.log"), **defaults)
        created.append(s)
        return s

    yield _make
    for s in created:
        s.shutdown(wait=False)
