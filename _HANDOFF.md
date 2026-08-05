# _HANDOFF.md — 会话交接文档

> ⚠️ 临时交接文档：交接完成后经确认删除（状态由 git 承载）。
> 日期：2026-08-05
> 当前状态一句话：**regime-driver 系统已完成 M-1/M-2/M-3 + 安全监控 + 架构 v2/v3/v4 + 流转决策并入策略 + tool/route/gate 确定性节点执行 + M-4 真实任务试跑 COMPLETE，核心功能可用，进入后续可选工作。**

---

## 1. 这是什么项目

**oc-meta / regime-driver**：一个 PyPI 就绪的 Python 包（`src/` 布局，约 2800 行），
实现 **L1 固定流程机器人（OA 系统）**：把 `workflow-regime/` 制度化流程编译成状态机，
驱动一个干净无插件的 opencode worker（L2），由只读审查者（L0）判定，独立线程监控。

- 开发环境：conda env `regime-driver`（python 3.12），本地 `pip install -e .`
- 运行依赖：pydantic、typer、rich（`infra/config.py` 支持 JSON/TOML 配置）
- 测试：`conda run -n regime-driver python -m pytest`（**119 项通过**，自主分支累计）
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
**分支**：master（本地，无远程 push）。
**测试基线**：99 项单测全绿；端到端真实 worker 多次 COMPLETE。
**git 状态**：工作区干净，自主分支 `autonomous-2026-08-05` HEAD `9c39cd7`（基线 `master` 最近提交 `798e0e8`）。

### 已完成（含 commit 引用）
- `M-1` worker 镜像 `opencode-worker:1.18.11`（无插件 + `--pure`）— `ede90c4`
- `M-2` L1 骨架（正式工程包，确定性门 + [WORK_DONE] 段协议 + 会话检查）— `a4fa6f0`
- `M-3` 审查者接入（严格 JSON 判定 + 带反馈重试 + skill 注入 + 任务控制文档）— `b01d9f6`
- 安全监控与紧急停止（独立监控线程 + 死循环检测 + abort 上报）— `102f6c6`
- 架构 v2 交接模型（结构化交接单 + 收敛检测 + 多轮质询）— `b8b5dac`
- 架构 v3 策略可编程（RolePolicy + 自评协议 + 脑容量交接）— `a8281d6`
- 架构 v4 角色通用化（内核角色无关，RoleRegistry/SessionRegistry）— `17ace1d`
- 流转决策并入 RolePolicy（废弃孤立 FlowStrategy）— `798e0e8`

### 核心能力清单
- 状态机：`core/state_machine.py` + `data/regime.json`（节点声明 role + type）
- 确定性门：`core/contract.py`（verdict/action 白名单、置信度、一致性）
- 交接单：`core/handoff.py`（inquiry/report/brain/role_transition + 收敛检测）
- 角色注册：`core/role.py`（Role/RoleRegistry，developer/reviewer 是默认实例）
- 策略：`core/policy.py`（RolePolicy：脑容量阈值 + 自评 + 流转决策 TransitionDecision）
- 会话管理：`app/session_manager.py`（SessionRegistry 按 role id）
- 脑容量自评：`app/session_lifecycle.py` + `app/self_assess.py`
- 安全监控：`app/monitor.py` + `core/repetition.py` + `app/meta_analyzer.py`
- 编排：`app/driver.py`（按 node.type 分流 + 锚点角色推断 + 流转决策）

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

1. **P1 自定义角色/流转策略端到端验证**：注册一个 `transition_mode=ROTATE` 的角色，
   验证"每节点新建 session + 交接文档"的流转路径（当前单测覆盖：`test_transition_rotates_role_session` +
   `test_transition_rotate_returns_rotated_role_set` + `test_anchor_transition_pins_session`）。
2. **P2 工作区物理隔离（部分完成）**：`core/policy.py` 的 `WORKSPACE_CONVENTIONS` 已通过 `workspace_for()`
   注入到 agent 指令提示（角色可见性提示），但 worker 挂载的物理隔离仍未实际调整（需 worker 重建）。
3. **P3 上帝对话框演进**：事件总线/邮箱、代际号、自省回路（远期，见 PLANNING）。
4. **P3 其它**：`_deadline` 字段仍恒为空（meta 研判的 deadline 未实际设置）；`main_loop` flow 仍不可达（死配置）。

- **已完成（2026-08-05 自主分支）**：tool/route/gate 确定性节点执行（`core/branching.py` 安全条件求值 +
  `core/tools.py` 确定性工具注册表，driver 按 node.type 真正分发）；工作区提示注入；流转修复
  （ANCHOR 显式处理、传 ctx、流转后刷新陈旧 dev 引用）；死代码清理；M-4 真实任务试跑 COMPLETE。

---

## 5. 关键约束

- 宪法层（定死，不可改）：安全监控、确定性门、收敛检测、节点预算。
- 用户特化（可自定义）：角色、策略、流转、交接模板。
- 内核不关心角色：developer/reviewer 只是用户注册实例。
- 节点 ≠ 角色：角色=session 分离，节点=skill 注入+需求分离。

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