# regime-driver 技术文档中心

> 本文件是 `docs/` 目录的**导航枢纽与治理章程**。
>
> **文档分工**：
> - `docs/` -- 设计文档与用户手册（根索引手册 + 5 个子目录）
> - 任务/过程文档（`TASK.md`、`WORK_PLAN*.md`、`HANDOVER.md`、`AGENTS.md`）在仓库根，不属本体系
> - `tasks_docs/`（若存在）-- 历史档案区（已废弃文档迁入）

---

## 一、目录结构

```
docs/
├── README.md              本文件（导航 + 治理章程）
├── WRITING_GUIDE.md       技术文档书写准则（强制）
├── KNOWN_LIMITS.md        已知限制
├── TECH_DEBT.md           技术债登记（问题清单）
├── CLI_REFERENCE.md       命令行/配置参考索引 → reference/
├── ARCHITECTURE.md        架构设计手册索引 → architecture/
├── SUBSYSTEM_DESIGN.md    子系统设计手册索引 → subsystems/
│
├── guide/                 入门教程（按序阅读）
│   ├── 00_environment.md
│   ├── 01_setup.md
│   ├── 02_first_run.md
│   ├── 03_design_flow.md
│   ├── 04_run_fleet.md
│   └── 05_god_dialog.md
│
├── howto/                 操作指南（按问题查阅）
│   ├── run-e2e.md
│   ├── debug-with-mock.md
│   ├── run-many-sessions.md
│   ├── god-dialog.md
│   ├── god-window.md
│   └── host-mode-agents.md
│
├── reference/             参考（命令/配置/规格/权限）
│   ├── 01_cli.md
│   ├── 02_configuration.md
│   ├── 03_flow_spec.md
│   ├── 04_permissions.md
│   └── 05_god_dialog_contract.md
│
├── architecture/          架构解释
│   ├── 01_principles.md
│   ├── 02_statechart_network.md
│   └── 03_boundary.md
│
└── subsystems/            子系统实现
    ├── 01_drive.md
    ├── 02_worker_isolation.md
    ├── 03_fleet.md
    ├── 04_supervisor.md
    ├── 05_chaos.md
    ├── 06_god_dialog.md
    ├── 07_god_dialog_carrier.md
    ├── 08_mock.md
    └── 09_testing_architecture.md
```

---

## 二、按角色的阅读路径

| 角色 | 推荐阅读顺序 |
|------|------------|
| **新加入的开发者** | 根 `README.md` -> `docs/guide/00_environment.md` -> `01_setup.md` -> `02_first_run.md` -> `CLI_REFERENCE.md` -> `ARCHITECTURE.md` |
| **写流程/用 CLI 的用户** | 根 `README.md` -> `guide/` 教程 -> `CLI_REFERENCE.md`（查命令/配置）-> `KNOWN_LIMITS.md`（查边界） |
| **要理解最终架构的人** | `ARCHITECTURE.md` -> `architecture/02_statechart_network.md` -> `architecture/01_principles.md` |
| **要改某子系统的人** | `SUBSYSTEM_DESIGN.md` -> 对应 `subsystems/NN_*.md` -> 源码 |
| **要了解技术债的人** | `TECH_DEBT.md`（开发前必读） |

---

## 三、文档治理纪律（强制）

### 3.1 单点真理

| 事实 | 唯一来源 |
|------|---------|
| 命令行/配置/流程规格 | `CLI_REFERENCE.md` + `reference/` |
| 架构设计 | `ARCHITECTURE.md` + `architecture/` |
| 子系统设计 | `SUBSYSTEM_DESIGN.md` + `subsystems/` |
| 语言级限制/边界 | `KNOWN_LIMITS.md` |
| 技术债 | `TECH_DEBT.md` |
| 测试基线 / 当前最紧要任务 | `TASK.md`（顶部） |

### 3.2 数字纪律（测试基线）

- 测试基线**只在 `TASK.md` 顶部**写一次。
- 其它文档**不得冻结具体测试通过数字**，统一用"以 `python -m pytest` 实跑为准"。

### 3.3 生命周期纪律

- 重大架构决策直接写入 `architecture/` 对应章节，不另立独立 ADR 文件。
- 已实现且无延迟项的设计内容可从任务文档中删除。
- 已废弃/历史文档**删除或迁入 `tasks_docs/`**，不在 `docs/` 内保留（历史在 git 中）。

### 3.4 跨文件一致性

`README.md`、`KNOWN_LIMITS.md`、`CLI_REFERENCE.md`、`ARCHITECTURE.md`、`SUBSYSTEM_DESIGN.md`
之间对同一命令/限制/架构立场的描述必须用**同一组事实**。

### 3.5 新增文档前的检查

- 新增概念前，先查 `ARCHITECTURE.md`/`SUBSYSTEM_DESIGN.md` 确认归属文档存在；若重复，扩展现有文档而非新建。
- 新增命令/配置前，先查 `CLI_REFERENCE.md` 与 `reference/`。

### 3.6 代码注释卫生纪律

> **核心原则**：代码注释只应注明**功能设计**与**已知问题**，不应承载项目过程信息（任务指针、设计代号、
> 历史叙述、文档章节引用）。过程信息属于任务文档与 git 历史，不属于代码。

**禁止在 `.py` 文件注释与 docstring 中出现**：任务文档指针（`见 TASK.md`/`WORK_PLAN`）、任务/里程碑编号
（`F1-F11`/`P0#`/`M-1`）、设计代号（`G1-G14`/`C1-C4`）、历史叙述（`原实现采用…`/`旧 bug`）、
文档章节号（`§6.1`）、文档路径指针（`docs/…`）。一律删除或改写为功能说明。

---

## 四、跨文档引用约定

- 文档间引用统一使用**仓库相对路径**。
- Markdown 超链接使用**相对于本文件**的路径，迁移文件时必须同步修正。

---

## 五、技术文档书写准则

全部技术文档的书写准则见 `docs/WRITING_GUIDE.md`（强制）。任何新增或修改 `docs/` 下文档时，必须以该文件为参考。
