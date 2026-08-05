# TASK.md — 自主运行任务控制文档

> 分支：`autonomous-2026-08-05`
> 日期：2026-08-05
> 模式：无人值守自主推进，最大自主权限，全部本地 commit（禁 push）。

## 目标

推进 regime-driver 后续候选工作（_HANDOFF.md §4），按优先级逐项实施，每项过质量门 + 全量测试零回归 + code-review，然后 commit 并接续下一项。所有推进方向都阻塞时停止并完整汇报。

## 候选清单（按优先级）

- [ ] P1 M-4 真实工程任务试跑（regime run 真实任务，验证多轮质询/脑容量交接/角色流转）
- [ ] P1 自定义角色 ROTATE 流转策略端到端验证（当前仅单测）
- [ ] P2 工作区物理隔离（开发者 code/ vs 审查者 work 根）
- [ ] P3 工具节点 tool/route/gate 确定性执行
- [ ] P3 上帝对话框演进（远期）

## 验证记录

- [DONE] 基线测试 | verified: 101 passed | 分支建立
- [DONE] P3 工具节点 tool/route/gate 确定性执行 | verified: 119 passed (+18) | 新增 core/branching.py, core/tools.py, tests/test_branching_tools.py；driver 按 node.type 分流真正执行
- [DONE] P2 工作区物理隔离（workspace_for + 指令注入工作区提示） | 同上一并按 | core/policy.py, driver._build_instruction
- [DONE] 修复 ANCHOR 未处理 / 传递 ctx / 流转后 dev 陈旧引用 | 同上一并按 | driver._apply_transition / run()
- [DONE] 清理死代码（WORK_DONE_RE / load_skill_description / Regime.node / status 硬编码 URL） | 同上一并按 | 多文件
- [REVIEW] 里程碑1 | 0 blockers, 1 warning(数值比较,已修) | 分支/tools/驱动/清理
- [DONE] P1 M-4 真实工程任务试跑 | verified: 真实 worker 全流程 COMPLETE | regime run 生成 utils.py/test_utils.py，双 reviewer judge advance(0.9)，pytest 2 passed；首跑因 reviewer LLM 瞬时停顿被 monitor 正确 abort(安全系统生效)
- [DONE] P1 自定义角色 ROTATE 流转策略端到端验证 | verified: 真实 worker 实跑 | 自建 agent-only 流程，RolePolicy(transition_mode=ROTATE) 的 reviewer 在 b→c 流转时 ledger 记录 decision=rotate，会话真实换新
- [ ] P3 上帝对话框演进（远期）

## 阻塞

（无）

## 自省记录

- [REFLECT] 2026-08-05 | progress: 里程碑1(tool/route/gate+工作区+流转修复,119测试) + M-4真实任务试跑COMPLETE | risk: reviewer LLM judge 瞬时停顿曾触发 monitor abort(安全系统按设计工作,非代码缺陷) | next: 更新交接/规划文档反映新状态 | escalate: no