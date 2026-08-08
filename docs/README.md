# 技术文档导航（docs/README）

> 本文档是 `docs/` 的**导航与索引**。它声明文档体系的"尺子"与阅读顺序，让读者按需取用。
> **书写准则是 `docs/WRITING_GUIDE.md`**（强制）；文档治理流程见 `skills/doc-governance/SKILL.md`。
> 任何新增/修改技术文档，对照 WRITING_GUIDE 自查并在此登记。

## 读者旅程

- **新用户 / 想跑一次**：根 `README.md` → 本文档 → `howto/`（实操）→ `KNOWN_LIMITS.md`（边界）。
- **理解最终架构**：`ARCHITECTURE-statechart-network.md`（对等多状态机网络）→ `DESIGN-god-dialog.md`（上帝对话框）→ `DESIGN-mock.md`（mock 调试）。
- **理解演进脉络**：`ARCHITECTURE-regime-driver.md`（v1 分层）→ `ARCHITECTURE-v2/v3/v4.md`（交接/工作区/角色通用化）→ `ARCHITECTURE-BOUNDARY.md`（宪法与用户特化边界）。
- **排查 / 开发**：`RESEARCH-thinking-timeout.md`（超时研究）→ `ARCHITECTURE-REVIEW.md`（早期诊断）。
- **健康 / 治理**：`TECH_DEBT.md`（**技术债，先读**）→ `KNOWN_LIMITS.md`（边界）→ `WRITING_GUIDE.md`（书写准则）。

## 文档清单

| 文档 | 类型 | 一句话覆盖 |
|---|---|---|
| `WRITING_GUIDE.md` | 准则 | 技术文档**强制书写准则**（尺子），Divio 四分法 + 骨架 + 行文 + 模板 + 红线 + 验收 |
| `ARCHITECTURE-regime-driver.md` | 解释 | v1 分层架构（cli→app→core/infra） |
| `ARCHITECTURE-v2.md` | 解释 | 交接模型（角色独立个体 + 结构化交接单） |
| `ARCHITECTURE-v3.md` | 解释 | 工作区 + 交接机制（脑容量自评、策略可编程） |
| `ARCHITECTURE-v4.md` | 解释 | 角色通用化（内核只认抽象角色 id） |
| `ARCHITECTURE-BOUNDARY.md` | 解释 | 宪法层（定死）vs 用户特化（可自定义）边界 |
| `ARCHITECTURE-statechart-network.md` | 解释 | **最终架构**：宪法→对等多状态机网络 + 信号协议 + 根不变量 |
| `ARCHITECTURE-REVIEW.md` | 解释 | 早期架构诊断与修复记录 |
| `DESIGN-regime-driver.md` | 解释 | regime-driver 设计（把制度化流程编译成状态机） |
| `DESIGN.md` | 解释 | 上帝对话框元系统早期规划 |
| `DESIGN-mock.md` | 解释 | mock 机制（无网络确定性调试） |
| `DESIGN-god-dialog.md` | 解释 | 上帝对话框设计与可行性定案 |
| `DESIGN-god-dialog-carrier.md` | 解释 | 上帝对话框载体决策（opencode 作载体 + 双路方案 + CLI 契约） |
| `GOD_DIALOG_OPERATOR.md` | 指南 | **上帝对话框操作手册**（供 opencode 消费的 CLI 契约全命令 + --json schema + 操作流程） |
| `RESEARCH-thinking-timeout.md` | 研究 | thinking 超时守护研究结论 |
| `KNOWN_LIMITS.md` | 参考 | 已知限制与边界（读者必读） |
| `TECH_DEBT.md` | 参考 | **技术债登记（问题清单，禁止 tricky/兼容层立场）——开发前必读** |
| `howto/` | 指南 | 实操指南（如何跑 E2E / 如何 mock 调试 / 如何用上帝对话框） |

## 书写纪律

- 新增概念：先答 A.4"概念归属唯一"——归属文档存在则扩展之，否则新建并在此登记。
- 人类手册区（本文档、howto/、KNOWN_LIMITS）**禁止**任何智能体元信息（agent 指令/skill 引用/工作流），见 WRITING_GUIDE Phase 0 红线。
- 事实矛盾裁决：源代码 > 测试 > 设计文档 > 标记"待验证"。变更历史归 git，文档只写当前状态。