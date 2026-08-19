# 文档地图

> 本站点按读者分层组织。从 [首页](index.md) 开始；这里是你需要的一切文档的索引。

## 使用者（用 regime-driver 跑任务）

### 用户指南

| 文档 | 内容 |
|---|---|
| [控制对话框（第一入口）](guide/00_dialog_control.md) | 为什么有它、好处、设计思路、功能、与体系配合 |
| [快速开始](guide/01_quickstart.md) | 用对话跑通第一个任务 |
| [你能做什么](guide/02_capabilities.md) | 能力一览（少量"为什么这样设计"） |
| [设计你自己的流程](guide/03_design_flow.md) | 用对话/简单方式设计流程 |
| [安装运行环境](guide/04_environment.md) | conda 环境、pip 安装、容器配方 |
| [配置模型与密钥](guide/05_setup.md) | worker/dialog-control 启动、模型密钥、`regime doctor` 自检 |
| [多工作区并行跑任务](guide/06_parallel.md) | 多工作区并行、隔离 |

### 操作指南（按问题查阅）

| 文档 | 内容 |
|---|---|
| [howto 总览](howto/README.md) | 操作指南导航 |
| [跑真实 E2E](howto/run-e2e.md) | 离线预跑 + 真实 worker E2E + 耗时解读 |
| [用 mock 离线调试](howto/debug-with-mock.md) | 无网络/无 LLM 下确定性调试 |
| [并发多 workflow](howto/run-many-sessions.md) | 并发与 session 管理 |
| [控制对话框操作](howto/dialog-control.md) | 监控/设计/启动/talk 用法 |

### 参考（查契约）

| 文档 | 内容 |
|---|---|
| [能力地图](capabilities.md) | 全部官方能力的索引（入口/场景/验证） |
| [CLI 参考总览](CLI_REFERENCE.md) | 命令/配置参考手册导航 |
| [CLI 命令契约](reference/01_cli.md) | 全部 `regime` 子命令签名/参数/权限 |
| [配置参考](reference/02_configuration.md) | 全部配置字段、环境变量、密钥 |
| [流程规格](reference/03_flow_spec.md) | regime.json / flow spec 结构 |
| [权限门禁](reference/04_permissions.md) | 权限等级与门禁规则 |
| [控制对话框契约](reference/05_dialog_control_contract.md) | 对话框命令速览与操作流程 |
| [已知限制](KNOWN_LIMITS.md) | 边界、未实现项、行为限制 |

## 开发者（理解/扩展 regime-driver）

| 文档 | 内容 |
|---|---|
| [架构总览](ARCHITECTURE.md) | 架构文档导航 |
| [总体设计思路](architecture/01_principles.md) | 七条架构原则与设计理念 |
| [最终架构（状态机网络）](architecture/02_statechart_network.md) | 对等状态机网络 + 看门狗 |
| [边界](architecture/03_boundary.md) | 系统边界与责任划分 |
| [分发与部署蓝图](architecture/04_distribution_blueprint.md) | 渠道/内容归属/用户路径 |
| [子系统总览](SUBSYSTEM_DESIGN.md) | 各子系统实现导航 |
| [发布教程（维护者）](guide/07_release.md) | 构建/发布/Pages 部署 |
| [书写准则](WRITING_GUIDE.md) | 文档书写纪律（强制） |

> **内部过程/审计文档**（技术债、耐久报告、供给就绪审查）属工程过程产物，不进公开文档站；
> 存于仓库 `tasks_docs/` 与根目录，供内部查阅。

> **说明**：机器专用的内部配置（skills、控制对话框助手、workflow-regime 流程模板）是机器专用内容，
> **不在本站点**。它们随 wheel 打包，经 `regime scaffold` 部署到运行环境。
