class KVClusterError(Exception):
    pass


class KeyNotFoundError(KVClusterError):
    pass


class ShardDownError(KVClusterError):
    pass


class ReplicationError(KVClusterError):
    pass


class InvalidKeyError(KVClusterError):
    pass


class StorageFullError(KVClusterError):
    pass
