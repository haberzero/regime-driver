# 改进工作清单与规划（WORK_PLAN 5）— 流程热编译/热加载基础设施 + 长期运行

> 日期：2026-08-09 · 状态：**F1–F11 已完成 + C1/C2/C4 已完成（2026-08-10，331 测试全绿）**；
> 剩余 L1–L3（长期运行耐久性）+ C3（opencode-go 延迟调优，依赖 L 期观测）
> 依据：用户方向——①长期运行用 OpenCode Go（刚配好的供应商）；②原始愿景层面，重点考虑
> **workflow 热编译检查与热加载**相关基础设施（含 CLI 等交互操作）；③其余由我按工程经验判断微调。
> 原则：每项过质量门 + 全量测试零回归 + code-review + commit，并同步 HANDOVER/TASK/WORK_PLAN。

---

## 0. 方向定案

- **模型**：默认 `deepseek-api/deepseek-v4-flash`（DeepSeek 官方 API），已在全实例统一（见 docs/guide/03_environment.md）。
- **主线转向"流程定义生命周期"**：目前 flow 只在启动时 `load_regime(path)` 读一次 + god `design` 内存注册。
  下一步建设 **热编译检查 + 热加载/热重载** 的一套基础设施——这是"可自我修改元系统"愿景的关键闭环
  （上帝对话框设计/编辑/重载 workflow，无需重启整个系统）。
- **长期运行（耐久性）**：获授权用 opencode-go 跑数小时，观察资源/泄漏/恢复。

---

## I. 热校验 / 热编译（Hot validate/compile）

> 目标：任何 flow 定义（启动、设计、重载、编辑）都经过即时校验，错误尽早暴露。

- **F1. 统一校验入口**：`core/validate.deep_validate`（已有）与 `StateMachine.from_dict` 已存在；
  补一个 `flow.compile_spec(raw)` 统一入口，任何来源（文件/JSON/NL/CLI）都走同一校验。
- **F2. 编辑即校验**：`regime flow validate <file>`；支持 `--watch` 对文件变更即时重校验（打印 ok/err）。
- **F3. 语义预检挂钩**：`preflight`（离线试跑）接到"设计/重载后"的流程，确保新 flow 一跑就死的情况被拒。

## II. 热加载 / 热重载（Hot reload）

> 目标：FlowRegistry 作为命名 flow 的单一真源，支持运行中加载/重载，原子替换，不损坏运行中的 workflow。

- **F4. `FlowRegistry`**（新 `src/regime_driver/flow.py`）：
  - 内建 flow（打包 regime.json）+ 用户设计 flow + 文件加载 flow 的统一注册表；
  - `load(path)` / `get(name)` / `list()` / `remove(name)` / `reload(name)`；
  - 归并 god dialog 现有的 `self.flows`（消除第二个真源）。
- **F5. 原子替换**：`reload` 先编译新版本（校验通过）再换入；**运行中的 workflow 用旧版本快照继续**，
  不因重载而 mid-flight 崩溃（版本化 + 快照语义）。
- **F6. 文件监视重载**：`regime run --flow <name> --watch <regime.json>` 或独立 `regime flow watch <file>`，
  变更 → 重校验 → 重载注册表（新任务用新版本；正在跑的不打断）。

## III. CLI 交互（热流程的一等交互面）

- **F7. `regime flow` 子命令**：`list / validate <file> / load <file> / reload <name> / rm <name> / inspect <name>`
  （`--json`、权限门禁：load/reload/rm 为写 RUN）。
- **F8. god 对话框接入**：A 路（god 容器）加 `regime flow` 插件工具；B 路（GodDialogUnit）加
  `flow list/validate/reload` 命令，与 `design`/`start` 打通——在对话框里完成"设计→校验→重载→跑"。

## IV. 安全反循环（热流程的反循环保证）

- **F9. 校验门禁**：任何 load/reload 必须先过 `deep_validate` +（可选）`preflight`，失败即拒、报错原因。
- **F10. 版本/快照**：flow 带版本号；`reload` 原子换指针；运行中 workflow 持旧快照。
- **F11. 反循环**：热重载不得引入非法环（validate 已查可达/环），max_total_nodes 兜底沿用。

## V. 长期运行（耐久性，用 opencode-go）

- **L1. 长时间 drive/fleet**：跑 2–4h 的 `regime drive` / `drive-many`（默认 opencode-go），
  观测：容器数、session 泄漏、journal/ledger 增长、内存、stall 恢复次数。
- **L2. 资源治理收尾**：`report --prune`/保留策略接入 drive 收尾；`worker prune` 定时回收空闲实例。
- **L3. 结果记录**：写一份耐久性报告（现象+影响+归属），更新 KNOWN_LIMITS。

## VI. 我的工程判断微调项（并入或按需）

- **C1. 覆盖率基线**：装 `pytest-cov`，`--cov-fail-under` 设为当前实际值，消除测试盲点。
- **C2. `regime doctor` 接入 god/web**：A 路 god 工具 + B 路 dialog `doctor` 命令（非监控，是自检）。
- **C3. 模型延迟治理**：opencode-go 下 judge 慢/停滞（舰队成员可能超时）——评审超时/重试参数调优。
- **C4. 主机模式 agent 模板**：补一段 `developer`/`reviewer` agent 配置模板片段（方式 B 易用性）。

---

## 验收标准（下 session 主线）

1. `regime flow list/validate/load/reload/rm/inspect` 可用，`--json` + 权限门禁。✅
2. 编辑/重载 flow 即时校验；非法/带环 flow 被拒且原因清晰。✅（`--watch` 编辑即校验）
3. 运行中 `regime run` 不受 `flow reload` 影响（原子替换 + 旧快照继续）。✅（旧 SM 不原地 mutate）
4. god A/B 路都能设计/校验/重载/启动 flow。✅
5. 长期运行（opencode-go）2h+ 无泄漏性增长；资源治理收尾生效。⬜（L1–L3 待下 session）
6. 全量测试零回归；HANDOVER/TASK/WORK_PLAN 同步。✅（333 passed，2026-08-10）

> 建议顺序：F1–F4（基础注册表+校验）→ F5/F6（原子替换+watch）→ F7/F8（CLI+dialog）→
> F9–F11（安全）→ L1–L3（长期运行）→ C1–C4（微调）。
