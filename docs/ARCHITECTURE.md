# regime-driver 架构设计手册

> 本手册是 regime-driver 的架构权威参考（"为什么这样"），覆盖设计原则与最终架构，按章节拆分至 `architecture/`。
> 命令行/配置参考见 `CLI_REFERENCE.md`；子系统实现见 `SUBSYSTEM_DESIGN.md`；已知限制见 `KNOWN_LIMITS.md`。

## 架构定位

regime-driver 采用**对等多状态机网络**：看门狗（无智能状态机 + 信号协议 + 根不变量运行时强制）监督
agentic 工作流单元；进程外 supervisor 提供独立时钟的自我监管。最终架构见 `architecture/02_statechart_network.md`。

## 章节索引

| 章 | 文件 | 主题 | 说明 |
|----|------|------|------|
| 01 | [01_principles](architecture/01_principles.md) | 架构原则与设计理念 | 层级/依赖规则/核心原则/角色与确定性门 |
| 02 | [02_statechart_network](architecture/02_statechart_network.md) | 对等多状态机网络（最终架构） | 信号协议、并行运行时、看门狗、根不变量、WorkflowUnit+StatechartDriver、消息机制 |
| 03 | [03_boundary](architecture/03_boundary.md) | 看门狗 vs 用户特化边界 | 内核定死 vs 用户可覆写的边界、运行时强制 |
| 04 | [04_distribution_blueprint](architecture/04_distribution_blueprint.md) | 分发与部署蓝图 | 渠道/内容归属/用户路径/卸载恢复/验证守卫 |

## 阅读路径

| 读者 | 推荐阅读顺序 |
|------|------------|
| 新开发者 | 01 -> 02 |
| 理解最终架构 | 02 |
| 做架构决策 / 边界 | 01 -> 03 |
