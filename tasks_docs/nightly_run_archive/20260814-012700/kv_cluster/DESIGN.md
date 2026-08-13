# 小型 KV 集群子系统 —— 方案设计定稿

## 模块结构
- `errors.py`：统一异常（KeyNotFoundError / ShardDownError / ReplicationError / InvalidKeyError / StorageFullError，均继承 KVClusterError）。
- `store.py`：单节点 KVStore（RLock 线程安全内存存储 + op-journal 崩溃恢复），以及顶层 facade `KVCluster`。
- `shard.py`：ShardManager，key→shard 确定性路由 + down 标记故障隔离。
- `replica.py`：ReplicaManager（primary + backup 同步复制、失败回滚、failover 升级并重建新 backup）。

## 设计决策 A：一致性模型 —— 选「主写备份同步复制（write-through）」
**备选**
1. 同步复制：写 primary 成功后再写 backup，两处都成功才返回；backup 写失败回滚 primary 并抛 ReplicationError。
2. 异步复制：只写 primary 即返回，backup 后台追赶。

**选型：同步复制。理由**
- 写后读一致是硬性边界：一次 set 返回成功即主备双写完成，随后任何 get（读 primary）必然读到该值。
- failover 不丢已提交写：backup 与 primary 始终一致，promote 后数据零丢失；复制失败（backup 未写）时 primary 有明确的回滚点（恢复旧值/删除新键），集群仍可用。

**被否：异步复制。不可接受点**
- primary 返回成功时 backup 可能落后；primary 一旦崩溃触发 failover，最近已确认的写会丢失，直接违反「写后读一致」与「failover 数据完整」。本项目一致性优先于写延迟，故否决。

## 设计决策 B：分片映射 —— 选「简单取模（crc32(key) % shard_count）」
**备选**
1. 一致性哈希：哈希环 + 虚拟节点 + 环查找。
2. 简单取模：对 key 取稳定整型哈希后 mod shard_count。

**选型：简单取模。理由**
- 确定性：crc32 跨进程稳定，key→shard 完全确定，便于测试与推理。
- shard 数量在集群创建时固定（KVCluster(shard_count)），无扩缩容/重分片需求，取模零数据迁移、实现与复杂度最低；配合 ShardManager 的 down 标志即实现故障隔离（仅 down 的 shard 抛 ShardDownError，其余 shard 不受影响）。
- 每个 shard 持有独立 KVStore/ReplicaManager，路由后互不干扰。

**被否：一致性哈希。不可接受点**
- 其核心收益「增删节点时最小化数据迁移」在本任务中无应用场景（shard 数固定），却引入哈希环、虚拟节点等额外复杂度，且 down 处理仍需额外标志位。复杂度与收益不匹配，故否决。

## 边界处理设计
- **并发**：所有存储访问经 RLock 线性化；8 线程并发 set/get/delete 同一集群，无数据丢失、无异常泄露。
- **恢复**：set/delete 均追加写 op-journal（单行 JSON），每次追加 flush（可配 fsync）；启动时回放 journal 重建状态；崩溃产生的撕裂尾部记录（未提交写）被丢弃，已提交写不丢。
- **隔离**：mark_shard_down 后仅该 shard 路由抛 ShardDownError，其余 shard 正常读写。
- **复制失败**：backup 写失败 → 回滚 primary（新键删除 / 旧键恢复原值）→ 抛 ReplicationError → 集群继续可用。
- **failover**：backup 提升为 primary，并按 primary 全量重建新 backup；journal 采用 generation 命名（`{role}.g{gen}.journal` + `role.json`），保证 failover 后重启仍能正确恢复主备角色与数据。

## 技术债 / 待决点
- journal 无压缩/快照，长期运行文件无限增长（后续可加 compaction / snapshot）。
- journal 无校验和，torn-tail 仅按「最后一行损坏即跳过」处理。
- failover 重建 backup 为 O(n) 全量拷贝，大数据量可改为流式/增量。
- 存储上限以 key 数计，未实现按字节容量限制。
- 副本数固定为 1 备份，未支持多副本 quorum。
