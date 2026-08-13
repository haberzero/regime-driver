import threading
import time

import pytest

from circular_buffer import BufferEmptyError, BufferFullError, CircularBuffer


class AtomicCounter:
    def __init__(self):
        self._value = 0
        self._lock = threading.Lock()

    @property
    def value(self):
        with self._lock:
            return self._value

    def increment(self):
        with self._lock:
            self._value += 1
            return self._value


def test_fifo_order():
    buf = CircularBuffer(3)
    for i in range(3):
        buf.write(i)
    assert [buf.read() for _ in range(3)] == [0, 1, 2]
    assert buf.is_empty()


def test_wrap_around_write_read_write():
    buf = CircularBuffer(3)
    for i in range(3):
        buf.write(i)
    assert buf.read() == 0
    assert buf.read() == 1
    buf.write(3)
    buf.write(4)
    assert buf.is_full()
    assert buf.read() == 2
    assert buf.read() == 3
    assert buf.read() == 4
    assert buf.is_empty()


def test_peek_is_non_destructive():
    buf = CircularBuffer(3)
    buf.write("a")
    assert buf.peek() == "a"
    assert buf.size() == 1
    assert buf.is_empty() is False


def test_full_write_raises_and_keeps_data():
    buf = CircularBuffer(2)
    buf.write(1)
    buf.write(2)
    with pytest.raises(BufferFullError):
        buf.write(3)
    assert buf.size() == 2
    assert buf.read() == 1
    assert buf.read() == 2


def test_overwrite_only_when_full():
    buf = CircularBuffer(3, overwrite=True)
    for i in range(3):
        assert buf.write(i) is None
    assert buf.write(3) == 0
    assert buf.read() == 1
    assert buf.write(4) is None
    assert buf.write(5) == 2
    assert buf.read() == 3
    assert buf.read() == 4
    assert buf.read() == 5
    assert buf.is_empty()


def test_overwrite_keeps_size_at_capacity():
    buf = CircularBuffer(2, overwrite=True)
    for i in range(5):
        buf.write(i)
    assert buf.size() == 2
    assert buf.is_full()
    assert buf.read() == 3
    assert buf.read() == 4


def test_empty_read_raises():
    buf = CircularBuffer(2)
    with pytest.raises(BufferEmptyError):
        buf.read()
    with pytest.raises(BufferEmptyError):
        buf.peek()


def test_invalid_capacity_raises():
    for capacity in (0, -1, -5):
        with pytest.raises(ValueError, match="capacity"):
            CircularBuffer(capacity)


def test_capacity_one():
    buf = CircularBuffer(1)
    assert buf.is_empty()
    buf.write(42)
    assert buf.is_full()
    assert buf.peek() == 42
    assert buf.read() == 42
    assert buf.is_empty()
    buf.write(7)
    assert buf.read() == 7


def test_state_flags():
    buf = CircularBuffer(2)
    assert buf.is_empty()
    assert not buf.is_full()
    assert buf.size() == 0
    assert buf.capacity() == 2
    buf.write(1)
    assert not buf.is_empty()
    assert not buf.is_full()
    assert buf.size() == 1
    buf.write(2)
    assert buf.is_full()
    assert buf.size() == 2


def test_concurrent_writers_readers_no_data_loss():
    capacity = 8
    total = 2000
    buf = CircularBuffer(capacity)
    barrier = threading.Barrier(4)
    read_count = AtomicCounter()
    written = []
    read = []

    def writer(start, count):
        barrier.wait()
        for item in range(start, start + count):
            while True:
                try:
                    buf.write(item)
                    written.append(item)
                    break
                except BufferFullError:
                    time.sleep(0.0001)

    def reader():
        barrier.wait()
        while read_count.value < total:
            try:
                item = buf.read()
                read.append(item)
                read_count.increment()
            except BufferEmptyError:
                time.sleep(0.0001)

    threads = [
        threading.Thread(target=writer, args=(0, total // 2)),
        threading.Thread(target=writer, args=(total // 2, total - total // 2)),
        threading.Thread(target=reader),
        threading.Thread(target=reader),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    assert not any(t.is_alive() for t in threads), "a thread failed to terminate"

    assert sorted(written) == list(range(total))
    assert sorted(read) == list(range(total))
    assert read_count.value == total
    assert buf.is_empty()


def test_concurrent_overwrite_never_raises():
    capacity = 4
    total = 2000
    buf = CircularBuffer(capacity, overwrite=True)
    barrier = threading.Barrier(4)
    writers_done = threading.Event()
    written = []
    read = []

    def writer():
        barrier.wait()
        for item in range(total):
            buf.write(item)
            written.append(item)

    def reader():
        barrier.wait()
        while not writers_done.is_set() or not buf.is_empty():
            try:
                item = buf.read()
                read.append(item)
            except BufferEmptyError:
                time.sleep(0.0001)

    writers = [threading.Thread(target=writer), threading.Thread(target=writer)]
    readers = [threading.Thread(target=reader), threading.Thread(target=reader)]
    for t in writers + readers:
        t.start()
    for t in writers:
        t.join(timeout=30)
        assert not t.is_alive(), "writer failed to terminate"
    writers_done.set()
    for t in readers:
        t.join(timeout=30)
        assert not t.is_alive(), "reader failed to terminate (starvation)"

    assert len(written) == 2 * total
    assert set(read) <= set(written)
    assert buf.is_empty()
