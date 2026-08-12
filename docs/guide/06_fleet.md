# 多工作区并行跑任务

本文教你用多个工作区并行跑任务，互不污染。
面向需要并发执行多个任务的用户。
覆盖工作区实例管理、舰队运行与资源回收。

## 你将会学到

- 用 `regime worker up` 为工作区启动隔离实例。
- 用 `regime drive-many` 并行跑多个隔离任务。
- 用 `regime worker prune` 回收空闲实例。

## 前置要求

- 已安装环境并完成配置（见《安装运行环境》《配置模型与密钥》）。
- 本机可运行 Docker 与 `opencode-worker` 镜像。

## 核心概念

`run-many` 只能在单个 worker 上并发多个流程。
它们共用文件系统，可能发生文件碰撞。
多实例工作区隔离把并发升级为真物理隔离。

每个工作区对应一个独立 opencode 实例。
实例是容器加独立挂载目录与独立端口。
同一工作区绝不启动第二个实例。
角色仍以 session 区分，原有模型不变。

```text
任务 A ──► 工作区 wsA ──► opencode-worker-wsA ──► 端口 4200 ──► 挂载目录 wsA/
任务 B ──► 工作区 wsB ──► opencode-worker-wsB ──► 端口 4201 ──► 挂载目录 wsB/
任务 C ──► 工作区 wsC ──► opencode-worker-wsC ──► 端口 4202 ──► 挂载目录 wsC/
            │               │                        │
            └───────────────┴────────────────────────┘
                        物理隔离，产物互不污染
```

跑在 A 的模型、读写 A 的文件，不会碰到 B 和 C。
（舰队实例端口从 4200 起分配，与默认单 worker 的 4097 不同——两者互不干扰。）

## 步骤

### 1. 启动一个工作区实例

`regime worker up` 确保某工作区有实例。
已存在则复用，不存在则新建。

```bash
conda run -n regime-driver regime worker up ws-algo
```

预期结果：输出该工作区的实例 base_url 与容器名。
再次执行同一命令，复用同一实例，不重复启动。

### 2. 查看实例列表

`regime worker list` 列出所有工作区实例。

```bash
conda run -n regime-driver regime worker list
```

预期结果：表格列工作区、容器、端口与健康状态。
可确认每个实例的端口与健康情况。

### 3. 跑一个隔离任务

`regime drive --workspace` 在指定工作区实例上跑任务。
它在该实例上启动完整的 drive 栈。

```bash
conda run -n regime-driver regime drive "实现 add(x,y)" --workspace ws-algo
```

预期结果：任务在该工作区实例上完成。
产物只写入该工作区的挂载目录。

### 4. 并行跑多个隔离任务

`regime drive-many` 并行跑多个任务。
每个任务跑在各自工作区实例上，物理隔离。
舰队共享一个 reporter journal，单一真源。

```bash
conda run -n regime-driver regime drive-many "实现 add(x,y)" "实现 mul(x,y)" --workspaces "wsA,wsB"
```

预期结果：输出每个任务的编号、工作区与结果。
`wsA` 与 `wsB` 各跑一个任务，互不污染。
`--workers N` 可限制同时跑的成员数。

### 5. 查看舰队汇报

舰队共享一个 reporter journal。
用 `regime report` 查看整支舰队的宏观汇报。

```bash
conda run -n regime-driver regime report --journal /tmp/fleet.jsonl
```

预期结果：输出整支舰队的聚合看板。
归属键区分每个任务的记录。

### 6. 回收空闲实例

`regime worker prune` 回收无会话的空闲实例。
这约束舰队资源增长，防止容器无限累积。
`--dry-run` 只报告不删除。

```bash
conda run -n regime-driver regime worker prune
```

预期结果：输出回收的实例数量。
`--max-instances` 可设置并发实例硬上限。

### 7. 停止并移除实例

`regime worker down` 停止并删除某工作区实例。
挂载目录保留在宿主机，容器内状态清除。

```bash
conda run -n regime-driver regime worker down ws-algo
```

预期结果：输出 removed 提示。
`worker list` 中不再出现该工作区。

## 你现在能做什么

- 能为工作区启动、列出与停止隔离实例。
- 能并行跑多个物理隔离的任务。
- 能回收空闲实例，控制舰队资源。

上帝对话框是主要使用入口（见《上帝对话框》）。

## 深入指引

- 工作区隔离设计：`../subsystems/02_worker_isolation.md`
- 舰队设计：`../subsystems/03_fleet.md`
- 混沌故障演练：`../subsystems/05_chaos.md`
