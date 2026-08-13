import threading


class BufferFullError(Exception):
    pass


class BufferEmptyError(Exception):
    pass


class CircularBuffer:
    def __init__(self, capacity, overwrite=False):
        if capacity <= 0:
            raise ValueError(f"capacity must be positive, got {capacity}")
        self._capacity = capacity
        self._overwrite = overwrite
        self._buffer = [None] * capacity
        self._head = 0
        self._tail = 0
        self._count = 0
        self._lock = threading.Lock()

    def write(self, item):
        with self._lock:
            if self._count == self._capacity:
                if not self._overwrite:
                    raise BufferFullError("buffer is full")
                overwritten = self._buffer[self._tail]
                self._tail = (self._tail + 1) % self._capacity
            else:
                overwritten = None
            self._buffer[self._head] = item
            self._head = (self._head + 1) % self._capacity
            self._count = min(self._capacity, self._count + 1)
            return overwritten

    def read(self):
        with self._lock:
            if self._count == 0:
                raise BufferEmptyError("buffer is empty")
            item = self._buffer[self._tail]
            self._buffer[self._tail] = None
            self._tail = (self._tail + 1) % self._capacity
            self._count -= 1
            return item

    def peek(self):
        with self._lock:
            if self._count == 0:
                raise BufferEmptyError("buffer is empty")
            return self._buffer[self._tail]

    def is_empty(self):
        with self._lock:
            return self._count == 0

    def is_full(self):
        with self._lock:
            return self._count == self._capacity

    def size(self):
        with self._lock:
            return self._count

    def capacity(self):
        return self._capacity
