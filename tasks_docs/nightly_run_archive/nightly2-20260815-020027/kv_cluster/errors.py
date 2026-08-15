"""Unified exception hierarchy for the kv_cluster subsystem."""


class KVClusterError(Exception):
    """Base class for all cluster-level errors."""


class KeyNotFoundError(KVClusterError):
    """Raised when an operation targets a key that is not present."""


class ShardDownError(KVClusterError):
    """Raised when an operation targets a shard that is marked down."""


class ReplicationError(KVClusterError):
    """Raised when a synchronous write to the backup replica fails."""


class InvalidKeyError(KVClusterError):
    """Raised when a key is not a valid non-empty string."""


class StorageFullError(KVClusterError):
    """Raised when a store has reached its configured capacity."""
