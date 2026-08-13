class KVClusterError(Exception):
    """Base class for all errors raised by the KV cluster subsystem."""


class KeyNotFoundError(KVClusterError):
    """Raised when a get/delete targets a key that is not present."""

    def __init__(self, key):
        self.key = key
        super().__init__(f"key not found: {key!r}")


class InvalidKeyError(KVClusterError):
    """Raised when a key is not a non-empty string."""

    def __init__(self, key, reason="key must be a non-empty string"):
        self.key = key
        super().__init__(f"invalid key {key!r}: {reason}")


class ShardDownError(KVClusterError):
    """Raised when accessing a shard that has been marked down."""

    def __init__(self, shard_id):
        self.shard_id = shard_id
        super().__init__(f"shard {shard_id} is down")


class ReplicationError(KVClusterError):
    """Raised when a synchronous write to the backup replica fails."""

    def __init__(self, message="replication to backup failed"):
        super().__init__(message)


class StorageFullError(KVClusterError):
    """Raised when a write would exceed the store's capacity limit."""

    def __init__(self, capacity=None):
        self.capacity = capacity
        if capacity is not None:
            super().__init__(f"storage full: capacity {capacity}")
        else:
            super().__init__("storage full")
