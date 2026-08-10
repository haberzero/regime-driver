# 进程外监督层架构

> 本文描述 `regime supervisor` 进程外监督层：T1 健康 / T2 停滞 / deadline / 纠正阶梯 / 元分析，
> 消费 worker SSE 事件流进 Reporter。面向需要理解或扩展监督/自愈机制的开发者。

---

## 1. 现状：为什么 M0 不能简单删除

旧 M0（`ops/supervisor.py` + `ops/stall-watchdog.js` + `ops/oc-task.py` + `ops/oc-run.sh` +
`ops/policy.json` + `ops/run-ledger.jsonl`）承担一个**无法被进程内 regime-driver 替代**的功能集：

| M0 功能 | 本质 | 能否被 regime-driver 进程内替代 |
|---|---|---|
| T1 进程健康轮询 + docker 重启（L4） | **进程外**、独立时钟、需 docker 控制权 | ❌ 进程内无独立时钟、无 docker 控制权 |
| T2 会话停滞（busy 但无新消息）→ abort | **进程外**、独立时钟 | ❌ 同上（"无进程外独立时钟"平台限制） |
| 期限强制（deadline 永不无限跑） | **进程外**、独立时钟 | ❌ |
| 纠正阶梯 L1–L5（abort/回退/重启/人工） | **进程外**编排 | ❌ |
| 元分析（模型判 verdict + 确定性门） | 独立模型复盘 | 可收编（复用 Reporter/模型调用） |
| stall-watchdog（进程内 thinking/静默停滞首道防线） | **进程内**插件 | ✅ 进程内 |
| oc-task 任务注册表 / 提交接口 | 任务管理 | ✅ 可收编 |

**结论**：M0 的核心价值（进程外独立时钟监督）是架构性必需的，不是死代码。彻底清理的正确路径是
**把监督功能作为一等公民收编进 regime-driver**（从"两套并存"变"一套系统"），再删除 M0 文件。

---

## 2. 目标架构：监督层作为 regime-driver 的一等公民

```
┌────────────────────────────────────────────────────────────┐
│  regime-driver（单一系统，消除双通道）                        │
│                                                            │
│  进程内（worker 内）：                                       │
│    · ConstitutionUnit 看门狗（根不变量 I1/I2/I3 强制）       │
│    · WorkflowUnit 状态机驱动                                 │
│    · Reporter 报告总线（journal + rollup，统一真源）          │
│                                                            │
│  进程外（宿主，独立时钟 + docker 控制）★ 新增一等公民：       │
│    · regime_driver.supervisor：                             │
│        T1 进程健康 + L4 docker 重启                          │
│        T2 会话停滞检测（独立时钟）                           │
│        期限强制（deadline）                                  │
│        纠正阶梯 L1–L5                                        │
│        元分析（复用 Reporter 上下文 + 确定性门）             │
│    · 任务模型：regime_driver.task（吸收 oc-task）             │
│        submit/list/status/stop/logs/clean + 只读 web         │
│    · 策略：Settings.policy（吸收 policy.json）               │
│                                                            │
│  报告总线：监督事件与 workflow 事件统一写入 Reporter           │
│   → `regime report --tasks-dir` 由 Reporter 自身任务视图取代   │
└────────────────────────────────────────────────────────────┘
```

### 2.1 监督层收编原则（避免重蹈"平行系统"覆辙）
1. **单一包内**：`regime_driver.supervisor`、`regime_driver.task` 作为包内模块，而非 `ops/` 独立脚本。
2. **单一真源**：监督事件（T1/T2/deadline/ladder/meta）全部经 `Reporter.ingest` 落同一 journal，
   与 workflow 事件同 schema（复用 `ReportRecord` + 归属键）。不再有独立 `run-ledger.jsonl`。
3. **单一策略**：`Settings.policy` 承载 deadline/模型/阈值/重试（吸收 `policy.json`），不再双份。
4. **任务视图**：`regime report` 的任务看板由 `regime_driver.task` 的注册表直接消费（吸收 oc-task），
   不再有两个 derive 逻辑（消除 `oc_tasks._derive` vs `oc-task.derive` 双写）。

### 2.2 明确职责边界（写入文档，防止未来再分裂）
- **进程内**（worker 内）：状态机驱动、turn 级 thinking/停滞首道防线、宪法看门狗根不变量、报告写入。
- **进程外**（宿主，独立时钟）：进程健康/重启、会话级停滞兜底、期限、纠正阶梯、元分析。
- 二者通过 **Reporter/journal（唯一事件真源）** 通信，而非各自独立记账。

---

## 3. 清理步骤（先建新、后切换、再删旧——不留功能缺口）

### 阶段 A：构建 `regime_driver.supervisor`（吸收 supervisor.py 功能）
- 把 supervisor 的 T1/T2/deadline/ladder/meta 逻辑迁入包内，进程外运行，独立时钟 + docker 控制。
- 事件写 Reporter（同 schema），替代 run-ledger.jsonl。
- 元分析复用包内模型调用与确定性门（吸收 `_gate`/`meta_analyze`）。
- 新增 supervisor 模块级测试（进程外逻辑纯化后可离线测 T1/T2 判定/ladder/gate）。

### 阶段 B：构建 `regime_driver.task`（吸收 oc-task）
- submit/list/status/stop/logs/clean + 只读 web，作为包内模块 + `regime task` CLI 子命令。
- 任务注册表路径可配（默认 `~/.regime/tasks`），由 `regime report` 直接消费。
- 消除 `ops/oc_task.py derive` 与 `infra/oc_tasks._derive` 双写 → 单一 derive。

### 阶段 C：切换与退役
- 更新 HANDOVER/命令速查/操作手册指向新接口。
- 停止旧容器监督（`opencode-autopilot` 挂载的 supervisor/stall-watchdog）→ 由新 supervisor 接管。
- **确认新监督功能经真实验证可用后**，删除旧 M0 文件：
  `ops/supervisor.py`、`ops/oc-run.sh`、`ops/oc-task.py`、`ops/run-ledger.jsonl`、`ops/policy.json`、
  `ops/stall-watchdog.js`、`ops/tasks/`、`ops/supervisor.out`、`ops/web.log`。
- 清理外围：TECH_DEBT G6/G7、HANDOVER §9 命令、docs 引用、`cli --tasks-dir` 改用新 task 视图。
- stall-watchdog 的进程内首道防线功能**保留**（它是进程内、合法），但作为包内插件/文档归位，
  不再作为"M0 平行系统"的一部分；若与 ConstitutionUnit 重复则合并（见 2.2 边界）。

### 阶段 D：验证与零残留
- 全量测试零回归 + 真实进程外 E2E（真跑一个任务，验证新 supervisor 的 T1/T2/deadline/ladder）。
- grep 确认 `supervisor.py`/`oc-task`/`oc-run`/`stall-watchdog`/`run-ledger` 无残留引用。
- 更新 `docs/README`、`HANDOVER`、`TASK`、`TECH_DEBT`（把 G6/G7 标为已清）。

---

## 4. 风险与护栏

- **不先删后建**：M0 是活生产控制面；必须先让新监督层真实验证可用，再退役旧容器监督，最后删文件。
- **真实 E2E 门槛**：新 supervisor 必须真跑一个任务验证 T1/T2/deadline/ladder 后才算完成，不能只单测。
- **单一真源纪律**：新监督事件必须走 Reporter，禁止再开第二个 `run-ledger`。
- **进程外时钟不可省**：绝不能为了"省事"把 T1/T2 塞进进程内（那会重蹈"无独立时钟"缺陷）。

---

## 5. 验收标准

1. `regime task submit/list/status/stop/logs/clean` 可用，任务看板进 `regime report`。
2. `regime supervisor` 进程外运行：T1/T2/deadline/ladder/meta 全部经 Reporter 记录。
3. 旧 M0 文件与外围引用全部清除，grep 零残留。
4. 全量测试零回归 + 真实进程外 E2E 通过。
5. TECH_DEBT G6/G7 标记已清，无"留半拆除状态"。

> 注：本设计是"系统化收编"路线。阶段 A/B/C 均为较大实现，按里程碑分步执行，每步过质量门 + 全量测试。
