# _HANDOFF.md — 会话交接文档

> ⚠️ 临时交接文档：交接完成后经确认删除（状态由 git 承载）。
> 日期：2026-08-06
> 当前状态一句话：**regime-driver 已彻底重构为对等多状态机网络（宪法=无智能状态机+信号协议+根不变量运行时强制），并完善多 workflow 并发 + 可视化(telemetry) + 原生完成检测 + 消息机制(订阅/黑板/线程池)；168 测试全绿，核心功能可用。**

---

## 1. 这是什么项目

**oc-meta / regime-driver**：一个 PyPI 就绪的 Python 包（`src/` 布局，约 2800 行），
实现 **L1 固定流程机器人（OA 系统）**：把 `workflow-regime/` 制度化流程编译成状态机，
驱动一个干净无插件的 opencode worker（L2），由只读审查者（L0）判定，独立线程监控。

- 开发环境：conda env `regime-driver`（python 3.12），本地 `pip install -e .`
- 运行依赖：pydantic、typer、rich（`infra/config.py` 支持 JSON/TOML 配置）
- 测试：`conda run -n regime-driver python -m pytest`（**168 项通过**，自主分支累计）
- 端到端：真实 worker 容器 `opencode-worker`（端口 4097）已多次验证 COMPLETE

**架构演进**（都在 `docs/` 有独立文档）：
- `ARCHITECTURE-regime-driver.md`：v1 分层（cli→app→core/infra）
- `ARCHITECTURE-v2.md`：交接模型（角色独立个体，结构化交接单）
- `ARCHITECTURE-v3.md`：工作区+交接机制（脑容量自评、策略可编程）
- `ARCHITECTURE-v4.md`：角色通用化（内核只认抽象角色 id）+ 流转决策并入 RolePolicy
- `ARCHITECTURE-BOUNDARY.md`：宪法层（定死）vs 用户特化（可自定义）边界
- `ARCHITECTURE-REVIEW.md`：早期架构诊断与修复记录

---

## 2. 当前工作状态

**主线**：regime-driver 系统本体（核心功能已可用）。
**分支**：`autonomous-2026-08-05`（本地，无远程 push）。
**测试基线**：168 项单测全绿；端到端真实 worker 多次 COMPLETE。
**git 状态**：工作区干净，自主分支 HEAD 为最新提交（baseline `master` 最近提交 `798e0e8`）。

### 已完成（含 commit 引用）
- `M-1` worker 镜像 `opencode-worker:1.18.11`（无插件 + `--pure`）— `ede90c4`
- `M-2` L1 骨架（正式工程包，确定性门 + [WORK_DONE] 段协议 + 会话检查）— `a4fa6f0`
- `M-3` 审查者接入（严格 JSON 判定 + 带反馈重试 + skill 注入 + 任务控制文档）— `b01d9f6`
- 安全监控与紧急停止（独立监控线程 + 死循环检测 + abort 上报）— `102f6c6`
- 架构 v2 交接模型（结构化交接单 + 收敛检测 + 多轮质询）— `b8b5dac`
- 架构 v3 策略可编程（RolePolicy + 自评协议 + 脑容量交接）— `a8281d6`
- 架构 v4 角色通用化（内核角色无关，RoleRegistry/SessionRegistry）— `17ace1d`
- 流转决策并入 RolePolicy（废弃孤立 FlowStrategy）— `798e0e8`

### 核心能力清单（对等多状态机网络 · 最终架构）
- 信号协议：`core/statechart.py`（Signal/SignalKind/StatechartUnit/Bus：同步/异步点对点、广播、主题订阅推送、emit 可订阅事件）
- 并行运行时：`app/statechart_runtime.py`（ThreadedUnit 独立线程+队列，Runtime 异步投递+根不变量强制）
- 运行编排：`app/statechart_driver.py`（单 workflow）+ `app/statechart_cluster.py`（多 workflow 并发）
- 工作流单元：`app/workflow_unit.py`（governed，单线程混合循环：drain 信号+轮询session+步进节点；原生完成检测+节点超时+线程池发派）
- 宪法状态机：`app/constitution_unit.py`（watchdog，REPORT 信号→死循环/卡死检测→STOP；读黑板做全局超时/预算/心跳）
- 根安全不变量：`app/runtime_invariants.py`（I1至少一watchdog/I2不可关STOP通道/I3元迭代上界，Runtime.start 强制）
- 黑板全局状态：`app/blackboard.py`（线程安全共享键值 + blackboard.changed 订阅）
- 遥测可视化：`app/telemetry.py`（订阅 watchdog_fire/blackboard.changed + 读黑板 render 状态表）
- 状态机/门/交接/角色/策略：`core/state_machine.py` `core/contract.py` `core/handoff.py` `core/role.py` `core/policy.py`
- 确定性节点：`core/branching.py`（安全条件求值）+ `core/tools.py`（确定性工具）
- 审查者：`app/reviewer.py`（严格 JSON 判定 + 门反馈重试；原生完成检测）
- 会话/脑容量：`app/session_manager.py` `app/session_lifecycle.py` `app/self_assess.py`
- **已删除（被取代）**：`app/driver.py`(RegimeDriver)、`app/monitor.py`、`app/meta_analyzer.py`、`app/segment_runner.py`

---

## 3. 自主运行配置

### 授权原则（必须遵守）
- **禁 push**：除非用户明确授权，禁止 `git push` 到任何远程；只本地 commit。
- **破坏性重构授权**：符合一般工程/架构原则且经分析确实优于此前的设计，允许破坏性重构（用户已多次指示"彻底重构，不用关心兼容"）。
- **自主推进偏好**：偏向无人值守，最大限度自我决定；只有确实无法决定才上报。
- **日志纪律**：所有自主决策详尽记录，"只记录，不断决"。

### 工作区注意
- worker 容器工作区 = `workspaces/opencode-worker`（宿主）→ `/root/work`（容器）。
- 测试/端到端会在该目录产生 demo*/ 产物，已 gitignore。

### 上报阈值
- `blocked` / `human_escalate` / 架构级方向调整 → 上报用户。
- 审查发现的 blocker 必须修复后才能标记完成。

---

## 4. 后续工作候选（按优先级）

1. **P1 排查 E2E 卡顿（下个 session 首要任务）**：官方 API judge 回合仅 4.8s（`ops/probe_judge_latency.py`），但完整 E2E 中 judge 常卡数分钟。已排除 provider 免费排队（系统全用官方 API）。**已推进（2026-08-06）**：
   - ✅ **新增 `ops/probe_node_timing.py`**："全流程节点耗时剖析"——测每个 node（agent/judge）的完整耗时构成（POST 等待 vs 原生 `time.completed` 生成 vs 轮询间隔 vs read_messages RTT）。实测：judge 隔离 8s（POST≈completed，read RTT 0.0s，干净）；agent 隔离 14s 但 `time.completed` 在 2s 出现而 POST 13.1s 才返回（11s 差，疑 agent 中间消息/工具调用，待查）。
   - ✅ **定位并修复 E2E judge 卡根因（静态缺陷）**：`workflow_unit._step_judge` 用 `_latest_text` 取最新 assistant 文本，但 real client **累积消息**（非 test fake 的替换），导致 judge 回复失败被 gate 拒绝后，在 re-prompt 生成窗口内**每个 poll 都重解析同一陈旧回复**并重复 `send_message` POST，塞满 dispatch pool（max_workers=2）→ 真卡死。修复引入 `_last_judged_key`（优先稳定 msg id）只处理一次/每回复；回归测试 `test_judge_waits_for_new_reply_not_stale`（无修复=ERROR/gate exhausted/prompts=3，有修复=COMPLETE/prompts=2）。168→169 测试全绿。
   - **剩余假设①**：真实 E2E judge prompt 含完整 skill + 开发者真实汇报（远大于 probe 简化 prompt），长推理致分钟级——需真实 E2E 复现确认（probe 可用 `--judge` 传真实 skill 验证）。
   - ✅ **E2E 复现并定位根因（2026-08-06）**：新增 `ops/e2e_debug.py`（包裹真实 client 逐操作计时）+ `ops/probe_judge_stall.py`（并发观察 reasoning/output）。**根因 = 发派线程池饱和**（非 judge 永久卡）：streaming `POST /message` 返回晚于 `message.completed`/`[WORK_DONE]` 标记（agent 实测约 11s 滞后），workflow 提前 advance 并发下一 node，前 node POST 仍占线程 → 2 个 trailing POST 占满 `max_workers=2` → design judge 发派**永久排队** → session 呈 "busy 无输出" → 宪法误判 stall 杀掉（原 E2E 卡数分钟）。
   - ✅ **修复发派序列化**：`workflow._dispatch` 先 await 前一 POST future（`_await_prior_dispatch`，等待期间 drain 信号、abort 时提前返回，保持 STOP 响应）再发下一 node。真实 E2E **两次 COMPLETE**（60.6s / 95.8s）；judge 长推理真实 21-60s（假设①确认为**长推理非永久卡**，stall_sec=120 有裕量）。回归 `test_dispatch_serializes_prior_post`（无修复 max_active=2 失败，有修复=1）。177 测试全绿。
2. **P1 mock 机制**：**已做基础（2026-08-06）**——避免 API/LLM 响应不确定性，无网络/无 LLM 确定性调试：
   - ✅ `src/regime_driver/testing/mock_client.py`：`MockClient` 实现与 `OpenCodeClient` 相同接口（drop-in 替换）。默认行为：reviewer 恒 advance 到当前节点首后继（传 `sm`）、developer 恒 `[WORK_DONE]`；规则 `rules[(agent, node)]` 按 `(agent,node)`→`(agent,None)` 二段匹配，支持 `reply`/`builder`/`delay`/`stall`/`error` 故障注入；**消息累积非替换**（忠实复现真实 judge 陈旧文本场景）。
   - ✅ `ops/mock_feasibility.py`：5/5 离线通过（完整流程 COMPLETE / 慢 judge 时序 / stall→宪法 STOP BLOCKED / judge 散文→gate exhausted）。
   - ✅ `tests/test_mock_client.py`（7 项）+ `docs/DESIGN-mock.md`。
   - **未做**：收敛现有测试内零散 FakeClient 到 MockClient；`ops/mock_worker.py` 离线运行时入口。
3. **P1 CLI 多 workflow/可视化接入**：CLI `regime run` 仍单 workflow（StatechartDriver）；多 workflow（StatechartCluster）+ telemetry 仅脚本/API。用户明确"CLI 之后再优化"。
4. **P2 工作区物理隔离**：`workspace_for()` 已注入指令提示，但 worker 挂载物理隔离未调（需 worker 重建）。
5. **P3 上帝对话框演进**：**已做 MVP（2026-08-06）**——实现为**对等状态机单元** `GodDialogUnit`（`app/god_dialog.py`，ThreadedUnit, role=human），订阅总线（`blackboard.changed`/`watchdog_fire`/`NOTIFY`）构建实时监控 + 事件日志；命令路由 status/start/inspect/watch/config/help + 自由文本→LLM（worker 线程，非阻塞解释，emit 回总线）。REPL 前端：`regime dialog` 命令 + `ops/god_dialog.py`。共享同一 Runtime（`StatechartCluster.register_unit`），故对话框原生订阅 workflow 指标。真实 LLM 解释 E2E 验证通过。**方案定案**见 `docs/DESIGN-god-dialog.md`（"对话框应在状态机体系内"=是，理由：永不阻塞不变量由 ThreadedUnit 满足、原生订阅总线、对等单元受根不变量约束）。**未做**：自然语言设计 workflow / 对特定 opencode session 独立内容交互 / 权限门控 / 监控区动态调整。
6. **P3 其它**：`_deadline` 字段仍恒为空；`main_loop` flow 不可达（死配置）。

**实验结论（2026-08-06）**：官方 API 基线快 4-6 倍于免费 provider（免费有排队）。系统已全用官方 API（settings.model/meta_model 默认 `deepseek-api/deepseek-v4-flash`）。`ops/probe_latency.py`/`probe_judge_latency.py` 可复用。

---

## 5. 关键约束

- **宪法层 = 无智能对等状态机**（可覆写：用户可注入自定义 watchdog/宪法单元）；**根安全不变量上移运行时强制**（`app/runtime_invariants.py`：I1 至少一 watchdog / I2 不可关 STOP 通道 / I3 元迭代上界，`Runtime.start` 违反拒启动）。
- 用户特化（可自定义）：角色、策略、流转、宪法、交接模板。
- 内核不关心角色：developer/reviewer 只是用户注册实例。
- 节点 ≠ 角色：角色=session 分离，节点=skill 注入+需求分离。
- 状态机线程 = 单线程混合循环（drain 信号 + 轮询 session + 步进节点），消除长阻塞（线程池发派）。

---

## 6. 待决项 / 待清理

- `_deadline` 字段恒为空（meta 研判的 deadline 未实际设置，靠消息时间戳）。
- monkey 用 `RolePolicy(transition_mode=ROTATE)` 构造时，dataclass 字段默认值会遮蔽类属性（测试里已用构造参数规避）。
- 交接文档（本文件）交接完成后删除。

---

## 7. 完整 goal objective 模板（可直接复制）

```
【regime-driver · 开发模式】主任务：继续推进 regime-driver 系统（见 _HANDOFF.md §4 候选）。

一、主线任务（按序）：
<从 §4 候选选一个，如 P1 真实任务试跑>（内容 + 验收标准）→ 下一个候选 ...
每完成一个任务用描述性 commit 提交（说明+验证计数），同步更新任务控制文档（HANDOVER/PLANNING），然后自动接续下一任务。

二、自主推进偏好（最高优先）：总体偏向无人值守，允许较大限度自我裁定与自我质询分析并尽可能推进。
只有经过最大限度反思/质询/分析后仍确实无法彻底自主决定的内容才造成阻塞。
上报阈值统一为"尽可能自主推进"——先穷尽自主手段，确实无法决定才上报。

三、交付纪律：本地 commit；禁止 push 到远程（硬原则）——除非用户明确指示允许 push。

四、工作流：每任务走 code-workflow + 质量门 + 全量测试零回归
（命令：conda run -n regime-driver python -m pytest -q）。

五、停止条件：先穷尽自主手段，仅当确实无法自主决定时才停止并记录 blocker。
硬性定时到达即停止并汇报。
```