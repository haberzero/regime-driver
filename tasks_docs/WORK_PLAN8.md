# regime-driver 设计有效性体系化重构规划（WORK_PLAN 8）

> 日期：2026-08-13
> 依据：深度核查（quality_deep_check.md）+ 设计有效性分析（三层脱钩）
> 核心目标：**让官方提供的每个功能都能被真实使用、被试用体系验证、被文档引导可达** ——
> 消除"功能供给面"与"官方配置 / 试用体系 / 对话框使用场景"之间的三层脱钩。
> 原则：少而深、具备代表性、可参考的深度（不追求数量）；每阶段走 code-workflow + 质量门 + 全量测试零回归 + general 只读 review。

---

## 0. 问题诊断摘要（三层脱钩）

| 层 | 现状 | 后果 |
|---|---|---|
| **功能供给** | 19 CLI + 17 插件工具 + 10 skills + 3 agents | 丰富但分散 |
| **官方配置** | scaffold 只部署 2 skills；developer 节点零 skill；config 无 skill↔节点示例 | 用户看不到能力全景，8 个 quality skills 无主 |
| **试用体系** | 12 任务全为"从零写单文件" | 只激活执行面，其余能力无表现机会 |
| **对话框** | 宣称"控制一切"但无能力地图引导 | 值守时不知道还能做什么 |

---

## 1. 总体目标与验收准则

**总目标**：建立一个"**能力 → 入口 → 场景 → 验证**"的完整闭环，使：
1. 每个官方功能都能映射到至少一个**试用任务**（验证它真的工作）
2. 每个功能都有**官方配置入口**（scaffold/config 让用户可达）
3. 每个功能都有**文档场景引导**（告诉用户何时用）
4. 试用体系能覆盖**重构/改 bug/跨模块/长任务/故障注入/流程设计**等代表形态

**验收准则（全局）**：
- 全量测试零回归（当前基线 415 passed）
- 试用套件：每类能力至少 1 个任务触发，全部任务 host 外部复验通过
- general 只读 review 无 blocker
- 能力地图文档与实现一致（可机器核对）

---

## 2. 分阶段实施计划

### 阶段 1：试用体系重构（能力覆盖引擎）— 最高优先

> 用户点名方向。目标：从"12 个单文件任务"改为**少而深、跨能力**的任务套件，
> 使每种 regime 能力都有真实任务触发。

**1.1 任务形态扩展（ops/quality_tasks.py）**

| 新任务类型 | 激活能力 | 需要 harness 改造 |
|---|---|---|
| 重构既有代码（预置半成品） | read_code/implement + code-odor | 预置文件进 worker |
| 修改既有 bug（预置带 bug 代码） | read_code 定位 + implement 修复 + code-review | 预置文件进 worker |
| 多文件/跨模块子系统 | 会话交接/上下文累积 + wrap 清理 | 多文件收集 |
| 长任务（触发 rotate/self-assess） | 会话管理 + 交接单 | 长 deadline + 交接断言 |
| 需设计决策的任务 | design 节点 + design-philosophy | 设计合理性断言 |
| 故障注入任务 | supervisor 阶梯 + chaos 联动 | 中途注入 + 恢复断言 |
| 流程设计任务 | flow 命令 + dialog design | 提交 flow + 运行验证 |

**1.2 harness 改造（ops/quality_run.py）**
- 新增 `seed_files` 字段：任务可声明预置文件（`docker cp` 进 worker /root/work/code）
- 新增 `expected_files` 多文件收集（当前只收 module+test_file）
- 新增 `assert_*` 断言钩子：交接发生断言、rotate 断言、恢复断言、流程注册断言
- 新增"能力覆盖报告"：运行后输出 `{能力 → 触发它的任务}` 映射表
- 保留宿主外部复验（pytest 独立验证产物质量）

**1.3 套件设计原则**
- **数量**：6-8 个精选任务（宁缺毋滥），每个激活 ≥2 种能力
- **代表性深度**：每个任务规格含明确边界 + 明确要激活的能力（写进 spec）
- **诚实失败**：保留首轮冷启动观察，但修复后应系统性减少误杀

**验收**：
- 新套件每任务：complete + host 外部复验通过 + 至少触发 1 项此前 0 使用的能力
- 能力覆盖报告：19 CLI 中至少覆盖 8 项此前未在夜间验证的核心命令

---

### 阶段 2：skill 注入对称化（产出方自律）

> 目标：解决"监督有门、产出无自律"的结构不对称。

**2.1 developer 节点挂质量 skill**
- `implement` 节点挂轻量质量 skill（复用 code-odor 或抽取其"异味自查"子集）
- `wrap` 节点挂 code-quality（交付自查：残留扫描/死代码/文档同步）
- 评估上下文成本：skill 全文注入 developer 提示词是否影响长任务（→ 可选精简版 SKILL）

**2.2 官方配置同步**
- `regime.json`：implement/wrap 节点加 `skill` 字段
- `scaffold.py:137` 部署清单扩展（按新挂载的 skill）
- `config.example.toml` 增加 skill↔节点映射注释示例
- `data/` 打包副本经 sync_templates 重同步 + 漂移守卫

**2.3 风险控制**
- skill 注入增加提示词长度（约 1-2K 字符/节点）→ 实测对节点耗时/完成率影响
- 若 code-odor 全文过重，创建 `developer-quality` 精简版（只保留自查协议）

**验收**：
- implement/wrap 节点提示词含质量 skill；run 真实任务验证 developer 自查行为
- 全量 415+ 零回归；scaffold 部署清单与 regime.json 一致

---

### 阶段 3：对话框成为"全能力引导枢纽"

> 目标：对话框从"少量命令"升级为"值守时所有能力的入口地图"。

**3.1 dialog `capabilities`/`help --all` 命令**
- 列出全部可用能力：CLI 命令 / 插件工具 / skills / agents
- 按场景分组：监控 / 设计 / 运行 / 质量 / 运维
- 每个能力附"何时用"一句话引导

**3.2 值守模式引导（官方 GUIDE）**
- `guide/00_dialog_control.md` 增加"值守模式"章节：
  什么时候打开对话框、对话框能调起哪些能力（flow 设计/质量审查/报告/态势）
- `howto/dialog-control.md` 增加"能力地图"操作示例
- 对话框打开即提示可挂 analyst 做态势简报（衔接 3.3）

**3.3 analyst/advisor 值守参与**
- 对话框 `status`/`watch` 时可选调 analyst 做态势摘要（复用现有 subagent）
- 展示"对话框 + 助手"组合场景，让 3 个 agents 在值守真实使用

**验收**：
- `regime dialog` 内 `capabilities` 输出与实现一致（能力地图单点真理）
- 值守模式文档 + 对话框 + analyst 组合 E2E 验证

---

### 阶段 4：官方配置与文档"能力地图"

> 目标：用户从任何入口都能看到能力全景与使用路径。

**4.1 新增 capabilities.md（能力全景图）**
- 表格：能力 → 入口（CLI/工具/对话框）→ 场景（值守/无人值守/一次性）→ 验证手段
- 每项标注"试用套件中哪个任务验证它"
- 文档单点真理：CLI 引用 01_cli.md、工具引用插件源码、skill 引用 workflow-regime

**4.2 官方文档场景标签**
- 每个 CLI/工具文档增加场景标签（值守/无人值守/一次性）
- `02_capabilities.md` 与 capabilities.md 建立互链

**4.3 config.example.toml 能力示例**
- 完整呈现 skill↔节点、report 保留策略、flow store 等可配置项
- 与 scaffold 部署保持一致性检查

**验收**：
- capabilities.md 中每个能力都能映射到入口 + 场景 + 验证任务（无孤儿）
- 文档与实现交叉核对脚本（新增 `ops/check_capabilities.py`）绿

---

### 阶段 5：试用套件重跑 + 能力覆盖验证（整合）

**5.1 夜间长跑**
- 用新套件（阶段 1）+ 新 skill 配置（阶段 2）+ 对话框能力（阶段 3）全链路重跑
- 记录：能力覆盖报告、完成率、lru_ttl 首轮是否不再误杀（验证 T2 修复生效）

**5.2 能力覆盖审计**
- 对照 capabilities.md 逐项核对：是否被试用任务触发、是否有入口、是否有文档
- 输出"未覆盖能力"清单 → 纳入下一迭代

**验收**：
- 能力覆盖报告显示：核心 CLI + 全部运行时 skills + 对话框枢纽均被真实使用
- 零静默失败；所有 blocker 修复后 commit

---

## 3. 依赖关系与里程碑

```
阶段1 (试用重构) ──┐
阶段2 (skill对称) ──┼──▶ 阶段5 (整合重跑+覆盖审计)
阶段3 (对话框)  ───┤
阶段4 (能力地图) ──┘
```

- 阶段 1 独立可先行（harness 改造不依赖其他阶段）
- 阶段 2/3/4 可并行（互不依赖，都依赖阶段 1 的验证框架）
- 阶段 5 是整合验证，依赖前四阶段全部完成

**里程碑**：
- M1：新试用套件跑通（6-8 任务，能力覆盖报告生成）
- M2：skill 对称化 + 官方配置同步（测试零回归）
- M3：对话框能力地图 + 值守引导（E2E 验证）
- M4：capabilities.md + 交叉核对脚本绿
- M5：整合重跑 + 覆盖审计 + 全量 commit

---

## 4. 风险与缓解

| 风险 | 影响 | 缓解 |
|---|---|---|
| skill 注入增加 developer 上下文成本 | 长任务变慢/超时 | 精简版 skill；实测阈值；必要时只挂 wrap |
| 重构/改 bug 任务预置文件耦合 harness | harness 复杂度上升 | seed_files 抽象；单测覆盖预置路径 |
| 对话框能力地图与实现漂移 | 文档失真 | capabilities.md 机器交叉核对脚本 |
| 试用任务难易不均 | 部分能力仍未覆盖 | 能力覆盖报告驱动迭代；每任务明确激活能力清单 |
| 长任务触发 rotate 的行为验证难 | 断言不准确 | 从 ledger 精确断言 rotate/handoff 事件 |

---

## 5. 每阶段质量门

- 每阶段完成：全量 pytest 零回归 + general 只读 review（无 blocker）+ TASK.md 记录
- 涉及配置/文档：`ops/sync_templates.py --check` 绿 + mkdocs build 干净
- 涉及真实运行：真实 worker 冒烟验证（至少 1 个代表性任务）
- 每阶段一个 commit，描述性消息（改动 + 验证计数）

---

## 6. 遗留与后续（不在本规划内）

- V-2 PyPI 发布（待用户）
- MaxListenersExceeded 纳入 doctor 检查（opencode 内部问题，低优先）
- workflow-regime 内部 skills 与 worker developer 的融合深度（长期演进）
