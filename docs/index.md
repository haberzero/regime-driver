# regime-driver

**把"制度"变成可执行、可监督、可复盘的工作流程机制。**

> **⚠️ 开发中 / 未发布（Experimental · In Development）**
>
> 本项目仍处于积极开发中的内部原型，尚无 v1.0 / 稳定 API 契约。接口可能不兼容变更，不保证向后兼容；
> 未经过外部安全审计。使用本软件造成的任何直接/间接损失，作者概不负责（见 License 与免责声明）。
> 若希望用于生产或作为依赖，请等待正式发布，或先联系维护者。

---

## 它是什么

**regime-driver 是一个"流程执行器"**：你定义一份**制度化流程**（JSON 状态机），它把这个流程
编译成可执行步骤，在一个干净、无插件的 opencode worker 上**逐节点驱动**完成任务，并由一个
**进程外的监督器**在旁看护。

它不是又一个"给一句话让它自由发挥"的 agent——而是**让一个流程机制替你管理 agent 干活**。

## 为什么这样设计

裸 opencode agent 无法保证：流程会被遵守、结果会被审查、卡死能被发现、过程能复盘。regime-driver
的核心理念是**智能负责自由裁量，机制负责确定性约束**：

| 裸 agent 的痛点 | regime-driver 的做法 |
|---|---|
| 任务自由发挥，无流程约束 | 流程每个节点是明确的一步，按序驱动 |
| 没有强制审查 | judge 节点由只读审查者判定，过不了确定性门就不前进 |
| 卡死/打转靠人盯 | 进程外 supervisor（独立时钟）检测停滞，自动纠正 |
| 无法复盘"为什么这样走" | 全程写报告日志 + 事件账本，可回放、可报告 |
| 无法批量/并发隔离 | 多工作区 / 舰队，每任务一个隔离实例 |

## 它具备什么功能

- **流程驱动**：把 `regime.json` / flow spec 编译成状态机，逐节点驱动（agent 干活 / judge 审查 /
  tool 确定性执行 / route 条件分支 / gate 硬门禁）。
- **一键自驱动栈**：`regime drive` 一条命令 = 执行器 + 进程外监督 + 报告总线。
- **独立监督**：进程外 supervisor 周期性看护 worker 健康、会话停滞、全局期限，按纠正阶梯自动处理。
- **可复盘**：`regime report` 宏观看板 + `regime events` 事件流 + `regime status --deep` 聚合态势。
- **并发与隔离**：多工作区物理隔离（每工作区一个 worker 实例）+ 舰队并发。
- **上帝对话框**：用自然语言对话式控制整个系统（监控/设计/启动/交互）。
- **热加载流程**：编辑流程文件即校验，运行中热重载。
- **资源治理**：session 自动清理策略（可配置）、journal 保留、版本漂移警告。

## 配置好之后，你可以做到

```bash
# 校验流程 → 离线预跑 → 跑一个真实任务 → 一键自驱动栈
regime validate
regime preflight --json
regime run "实现 add(x,y) 并写 pytest" --base http://127.0.0.1:4097
regime drive "实现 add(x,y) 并写 pytest" --reporter /tmp/rep.jsonl

# 监督、复盘、对话控制
regime status --deep
regime report --journal /tmp/rep.jsonl
regime dialog --live --base http://127.0.0.1:4097
```

一个受监管的 `drive` 任务，会：离线预检 → 起执行器线程 → 起进程外 supervisor（看健康/停滞/
期限）→ 两者共享一份报告日志 → 完成后注册为受监管任务。你可以随时 `regime task list/status`
查看、停止。

## 官方提供什么

- **开箱即用的官方模板**：agent 模板、skills、god 助手、docker 配方——随 wheel 打包，
  `regime scaffold` 一条命令生成全套配置。
- **CLI**：`regime` 命令集（run/drive/report/dialog/flow/worker/chaos/doctor/scaffold/…）。
- **文档站**：你正在读的这份（用户指南 / 开发者指南 / 参考）。
- **容器配方**：`ops/up.sh` 一键构建 + 拉起 worker/god 容器。
- **许可**：MIT License（Copyright © 2026 Nan Shi 施楠）。

---

## 从这里开始

- **我是使用者，想最快用上** → [上帝对话框（第一入口）](guide/00_god_dialog.md) 然后 [快速开始](guide/01_quickstart.md)
- **我想看全部能力** → [你能做什么](guide/02_capabilities.md)
- **我是开发者**（想理解/扩展它）→ [总体设计思路](architecture/01_principles.md) · [子系统实现](SUBSYSTEM_DESIGN.md) · [流程规格](reference/03_flow_spec.md)
- **我想看边界** → [已知限制](KNOWN_LIMITS.md)
- **我想查技术细节**（命令/配置/JSON）→ [CLI 参考](reference/01_cli.md) · [配置参考](reference/02_configuration.md) · [流程规格](reference/03_flow_spec.md)

> 本站导航按读者分层：**使用者** → "用户指南"（能做什么 + 少量为什么）与"参考"（查技术细节）；
> **开发者** → "开发者指南"。供 agent 执行的内部配置（skills / god 助手 / workflow-regime）**不在此站点**，
> 保持机器专用。
