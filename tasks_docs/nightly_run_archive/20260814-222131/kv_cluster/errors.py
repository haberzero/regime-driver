"""统一异常：kv_cluster 子系统的全部可预期错误。"""


class KVClusterError(Exception):
    """所有 KV 集群异常的公共基类。"""


class KeyNotFoundError(KVClusterError):
    """请求的键不存在。"""


class ShardDownError(KVClusterError):
    """请求被路由到处于 down 状态的 shard。"""


class ReplicationError(KVClusterError):
    """写操作未能同步复制到 backup。"""


class InvalidKeyError(KVClusterError):
    """键不合法（非 str、空串等）。"""


class StorageFullError(KVClusterError):
    """存储达到上限，无法容纳更多键。"""
