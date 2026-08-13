import os
import threading
import zlib

import replica
import store
from errors import ShardDownError


class ShardManager:
    def __init__(
        self,
        shard_count,
        replication=True,
        journal_dir=None,
        limit=None,
        backup_limit=None,
        fsync=True,
    ):
        if shard_count < 1:
            raise ValueError("shard_count must be a positive integer")
        self._shard_count = shard_count
        self._replication = replication
        self._lock = threading.RLock()
        self._down = set()
        self._shards = []
        for index in range(shard_count):
            if replication:
                shard = replica.ReplicaManager(
                    index,
                    journal_dir=journal_dir,
                    limit=limit,
                    backup_limit=backup_limit,
                    fsync=fsync,
                )
            else:
                journal_path = None
                if journal_dir is not None:
                    journal_path = os.path.join(
                        journal_dir, f"shard{index}_plain.g0.journal"
                    )
                shard = store.KVStore(
                    journal_path=journal_path, limit=limit, fsync=fsync
                )
            self._shards.append(shard)

    @staticmethod
    def _shard_for(key, shard_count):
        return zlib.crc32(key.encode("utf-8")) % shard_count

    def _route(self, key):
        store._validate_key(key)
        index = self._shard_for(key, self._shard_count)
        with self._lock:
            if index in self._down:
                raise ShardDownError(f"shard {index} is down")
        return index

    def get(self, key):
        return self._shards[self._route(key)].get(key)

    def set(self, key, value):
        self._shards[self._route(key)].set(key, value)

    def delete(self, key):
        self._shards[self._route(key)].delete(key)

    def has(self, key):
        return self._shards[self._route(key)].has(key)

    def size(self):
        with self._lock:
            return sum(shard.size() for shard in self._shards)

    def _check_index(self, shard_id):
        if not 0 <= shard_id < self._shard_count:
            raise ValueError(f"invalid shard id {shard_id!r}")

    def mark_shard_down(self, shard_id):
        with self._lock:
            self._check_index(shard_id)
            self._down.add(shard_id)

    def mark_shard_up(self, shard_id):
        with self._lock:
            self._check_index(shard_id)
            self._down.discard(shard_id)

    def failover(self, shard_id):
        with self._lock:
            self._check_index(shard_id)
            if not self._replication:
                raise ValueError("replication is disabled; failover is not supported")
            self._shards[shard_id].failover()

    def status(self):
        with self._lock:
            result = []
            for index, shard in enumerate(self._shards):
                if self._replication:
                    result.append(
                        {
                            "shard": index,
                            "state": "down" if index in self._down else "up",
                            "replicated": True,
                            "primary_size": shard.size(),
                            "backup_size": shard.backup_size(),
                            "backup_healthy": shard.backup_healthy(),
                        }
                    )
                else:
                    result.append(
                        {
                            "shard": index,
                            "state": "down" if index in self._down else "up",
                            "replicated": False,
                            "primary_size": shard.size(),
                            "backup_size": None,
                            "backup_healthy": None,
                        }
                    )
            return result

    def close(self):
        with self._lock:
            for shard in self._shards:
                shard.close()
