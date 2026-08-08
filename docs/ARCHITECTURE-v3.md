# regime-driver 工作区与交接机制设计（v3）

> ⚠️ **已废弃（历史文档）**：已被 `ARCHITECTURE-statechart-network.md`（对等多状态机网络）取代。
> 当前架构以 statechart-network 为准；本文仅作演进脉络参考。
>
> ---
>
> 状态：~~设计定稿，实施完成（P1-P4）~~（已废弃）
> 日期：2026-08-04
> 背景：v2 确立了"角色是独立个体，靠交接单协作"。本设计细化**工作区模型**、
>   **交接文档体系**、**session 自评协议**、**策略可编程**。
> 关联：`docs/ARCHITECTURE-v2.md`（交接模型）、`docs/DESIGN-regime-driver.md`（OA 设计）
> 实施结果：新增 `core/policy.py`（RolePolicy 策略抽象 + SelfAssessment + 默认策略）、
>   `app/self_assess.py`（自评协议 + 独立重试）；`session_lifecycle.py` 改为自评驱动
>   （策略阈值 + 自评 + decide）；`handoff.py` 扩展 kind（brain_normal/brain_urgent/
>   role_transition）；`driver._check_session_capacity` 自评驱动。96 单测通过。

---

## 1. 核心前提（用户原话要点）

1. **任何 session 都是"会累的人"**：上下文窗口 + 轮次增长 → 模型劣化，不能无限使用。
2. **不能把 agent/session 当作可无限持续的人员**。
3. **交接是"询问 session 自己"**，不是机器人硬性判断。
4. **session 有"工作态/空闲态"两态**：用户发要求 → 自动工作 → 汇报 → 回到等待输入。
   "停止工作" = session 回到空闲态的时刻 = 唯一允许强制交接的时机。

---

## 2. 工作区模型（角色可见性）

### 2.1 结构
```
/root/work                      ← 共享根（审查者视角，全貌）
├── handoff/                    ← 交接文档中心（robot 管理，开发者不可见）
│   ├── brain/                  ← 脑容量交接（同角色换 session）
│   │   ├── <id>_normal.md
│   │   └── <id>_urgent.md
│   ├── transition/             ← 角色流转交接（审查者→审查者）
│   │   └── reviewer_<n>.md
│   └── reports/                ← 开发者详尽任务报告（给新审查者）
└── code/                       ← 开发者工作区（只在此工作）
    ├── <项目代码> src/ docs/ tests/
    └── HANDOFF.md              ← code 区交接手册（开发者写/读，同角色脑容量交接）
```

### 2.2 角色视角
| 角色 | 工作目录 | 可见 | 写权限 |
|---|---|---|---|
| 开发者 | `/root/work/code` | code/ 内 | code/ 内（HANDOFF.md + 代码） |
| 审查者 | `/root/work` | code/ + handoff/ | handoff/（交接收录） |

### 2.3 关键原则
- **开发者只挂载/工作在 code/**，不知道 code 之外（利用 opencode session 的
  `directory` 机制——session 启动位置就是工作区）。
- **审查者**在 work 根，能读 code + handoff。
- 审查者读 code/HANDOFF.md **无负面**（审查者不改代码）。
- 审查者写 handoff/ 交接文档，开发者不可见（不干扰）。

### 2.4 代码共享
- 开发者提交代码到 git（commit）。
- 审查者**直接读同一个 code/ 目录**（无需 git pull 同步，同根共享）。
- 采纳用户方案：代码共享，审查者直读。

---

## 3. 交接文档体系（统一的 Handoff，按用途分 kind）

| 交接类型 | kind | 时机 | 生产者 | 内容 | 载体 |
|---|---|---|---|---|---|
| 脑容量-正常 | `brain_normal` | 40% + 里程碑可保存 | 当前 session | 自评 + 交接文档 | handoff/brain/ 或 code/HANDOFF.md |
| 脑容量-紧急 | `brain_urgent` | 70% + 停止工作后 | 当前 session | 紧急交接（模板不同） | handoff/brain/ |
| 角色流转 | `role_transition` | 审查者 A→B | 旧审查者 A | 记录报告 + 开发者详细报告 | handoff/transition/ |
| 任务报告 | `report` | 角色流转时 | 开发者 | 详尽任务报告 + 近期工作 | handoff/reports/ |

### 3.1 脑容量交接（同角色，纵向）
- **40%**：开始自评。若里程碑未完成 → 继续推进 + 记 flag；里程碑可保存时，
  session 为下一个 session 写交接（HANDOFF.md），然后切换。
- **70%**：非硬掐断。session 停止当前工作（回到空闲态）后，机器人**要求立刻交接**，
  用**紧急模板**（与正常模板不同）。
- 交接文档由 session **直接在工作区书写**（code/HANDOFF.md 或 handoff/brain/），
  不需机器人做文件传递。

### 3.2 角色流转交接（跨角色，横向）
- 审查者推进 → 必然涉及 session 切换（不同审查者不在同一 session）。
- **与脑容量交接可并行**，执行顺序：**先做流程推进**。
- 新审查者 B 衔接：
  - 开发者提供**详尽任务报告 + 近期工作**（handoff/reports/）
  - 旧审查者 A 提供**相关记录报告**（handoff/transition/reviewer_<n>.md）
- **关键约束**：审查者流转/节点推进时，**开发者 session 禁止切换**（不允许"双失忆"，
  即便开发者有交接文档也不行）。开发者是"稳定锚点"。

---

## 4. Session 自评协议

### 4.1 触发
- 阈值渐进：40% 开始自评，70% 强制交接。
- 开发者和审查者阈值**可不同**（审查者默认更严格），策略开放给用户。

### 4.2 自评契约（确定性字符，可解析）
```json
{
  "verdict": "CONTINUE" | "ROTATE" | "HANDOFF_NOW",
  "remaining_rounds_estimate": 3,
  "milestone_reachable": true,
  "reason": "..."
}
```

### 4.3 自评重试
- 独立的自评重试（不绑定质询轮数 / dialogue rounds）。
- 返回不可解析 → 反馈 session 要求重试，上限独立配置。

### 4.4 机器人动作（固定代码）
```
自评 verdict:
  CONTINUE     → 继续推进，记录 remaining_rounds_estimate
  ROTATE       → 里程碑可保存时：写交接 → 切换 session
  HANDOFF_NOW  → 停止工作后：紧急交接（70% 模板）→ 切换
```

---

## 5. 策略可编程

### 5.1 分层
- **策略 = Python 代码 + 对话模板**（用户可写，参考策略预置）。
- 现阶段用户只有我们自己，但设计为可扩展。

### 5.2 策略覆盖点
| 策略点 | 默认（参考） | 用户可覆盖 |
|---|---|---|
| 阈值（40%/70%） | 开发者 40/70，审查者更严 | ✅ |
| 自评触发 | 按阈值 | ✅ |
| 交接消息模板 | 预置中文模板 | ✅ |
| 交接时机决策 | ROTATE 条件 | ✅ |
| 紧急交接模板 | 与正常不同 | ✅ |

### 5.3 抽象层
```
RolePolicy(Protocol):
    context_threshold_normal: float   # 40%
    context_threshold_urgent: float   # 70%
    def self_assess(self, ctx) -> SelfAssessment
    def handoff_message(self, kind) -> str   # 模板
    def should_rotate(self, assessment) -> bool
```
- 开发者/审查者各一个策略实例（同名抽象，不同参数/逻辑 = "只有写出的策略不同"）。

---

## 6. 与现有代码的衔接

| 现有 | 演进 |
|---|---|
| `app/session_lifecycle.py`（脑容量检测） | 升级为"自评驱动"（调协议，非硬阈值） |
| `core/handoff.py`（Handoff） | 扩展 kind：`brain_normal`/`brain_urgent`/`role_transition` |
| `app/reviewer.py` | 加自评方法（返回确定性字符） |
| `app/session_manager.py` | rotate 时按 kind 选模板 |
| 新增 `core/policy.py` | 策略抽象 + 默认策略 |
| 新增 `app/self_assess.py` | 自评协议 + 独立重试 |

---

## 7. 里程碑（本次设计落地）

| 阶段 | 内容 | 状态 |
|---|---|---|
| P1 | `core/policy.py` 策略抽象 + 默认策略（开发者/审查者不同阈值） | ✅ |
| P2 | 自评协议 + `app/self_assess.py`（确定性字符 + 独立重试） | ✅ |
| P3 | `core/handoff.py` 扩展 kind（brain_normal/brain_urgent/role_transition） | ✅ |
| P4 | `session_lifecycle.py` 改为自评驱动（策略阈值 + 自评 + decide） | ✅ |
| P5 | 工作区目录约定（`WORKSPACE_CONVENTIONS` 参考常量；worker 挂载调整留待重建） | ⏳ 部分 |