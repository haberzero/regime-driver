# 多 opencode 实例工作区隔离

> 本文描述 `regime worker` 的多实例工作区隔离：每工作区一个 opencode 实例（物理隔离），
> 同一工作区的实例不重复启动，工作区内的角色仍以 session 区分。面向需要并发 self-driving 的开发者。
> 测试：`tests/test_worker.py`（10）+ 真实 E2E（多实例隔离）。

## 为什么是"按实例"而非"按 session"

已探明：本 opencode 版本（1.18.11）的 `POST /session` 的 `directory` 字段是 **project 级**的，
实测恒解析为服务器自身 cwd（`/root/work`），**无法按 session 设 cwd**。因此"同一 worker 内
按 session 隔离工作区"不可能。改为**每工作区一个 opencode 实例**：

- 每个实例 = 一个 `opencode-worker` 容器 + **自己的挂载工作区目录** + 独立端口；
- **同一工作区绝不启动第二个实例**（no-duplicate 不变量，经 docker 查询持久保证）；
- 实例内角色（developer/reviewer/god）仍以 **session** 区分（原有每角色一 session 模型不变）。

## 架构

```
regime_driver.worker.WorkerPool            —— 管理 workspace -> instance 映射
  ├─ slugify(ws) / instance_name(ws)       —— 确定性容器名（纯函数，可测）
  ├─ work_dir_for(ws)                      —— 工作区目录（REGIME_WORKSPACE_ROOT/<slug>）
  ├─ ensure(ws)  → 复用已有实例（无重复）或新建（唯一挂载 + 端口 + 等健康）
  ├─ get(ws)     → 现有实例（docker 查询，跨进程持久）
  ├─ list() / remove(ws)                   —— 列出 / 停止并移除
  └─ _run_docker(·)                        —— docker + sg docker 回退（stale-shell）
```

- **映射持久化在 docker**（容器名 `opencode-worker-<ws>`），不变量跨进程成立。
- **端口**：从 `REGIME_WORKER_PORT_BASE`（默认 4200）起分配，复用已存在实例的端口，
  新实例找第一个空闲端口。
- **密钥**：`WorkerPool._resolve_key` 显式参数 > `DEEPSEEK_API_KEY` env >
  `~/.regime/keys/deepseek.key`（与 `ops/up.sh` 一致）。

## 集成

- **CLI `regime worker`**：`list` / `up <ws>` / `base <ws>` / `down <ws>`。
- **`regime drive --workspace <ws>`**：通过 `WorkerPool().ensure(ws)` 解析该工作区的
  实例 base_url，再在其上跑整套 drive 栈（执行器+supervisor+reporter）。未指定 `--workspace`
  则回落 `--base`/默认（单共享 worker，向后兼容）。

## 验证（真实 E2E）

1. `regime worker up ws-algo` → 起实例（容器 `opencode-worker-ws-algo`，端口 4200）。
2. `regime worker up ws-algo` **再次** → 复用同一实例（同端口，未重复启动）✅。
3. `regime worker up ws-infra` → 第二个独立实例（端口 4201，独立挂载）✅。
4. `regime drive ... --workspace ws-algo` → 真实任务 **COMPLETE**（119.6s, supervisor=workflow_done）。
5. 产物 `ws_nine.py` **仅出现在** `/…/ws-algo/code/`；`ws-infra` 与默认 worker `/root/work`
   均无 → **物理隔离成立** ✅。

## 边界

- 每实例是一个容器，多工作区 = 多容器（资源成本随实例数线性增）。
- `regime worker down <ws>` 会**停止并删除**该实例容器（及其未提交的容器内状态；
  挂载目录在宿主机 `REGIME_WORKSPACE_ROOT` 保留）。
- 默认（无 `--workspace`）仍用单共享 worker（向后兼容）；需要隔离的并发任务显式指定 `--workspace`。
