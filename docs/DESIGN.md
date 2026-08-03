# 自主工作体系：元层（Meta-Layer）设计与分析

> 目标：以 Docker 为基本运行单元，在「opencode + goal-plugin」之上叠加一个具备
> **元纠正、自我改善、全局分析、元流程分析**能力的独立监督层，解决"模型 thinking 卡死
> 而内嵌插件无法纠正"的问题。

---

## 一、opencode-goal-plugin 源码分析（设计/思路/决策）

### 1.1 整体架构
- 单文件 `src/goal-plugin.js`（约 5000 行），导出 `server(ctx, options)` 工厂，返回**钩子映射**。
- 状态持久化到项目 `.opencode/goals/state.json.sessions/<sha256(sessionID)>/state.json`，
  外加**追加式账本** `state.json.ledger.jsonl`，崩溃后可从账本重建活动目标。

### 1.2 它使用的 opencode 能力面（全部为"事件/钩子"，无独立后台定时器）
| 钩子 | 用途 |
|---|---|
| `event` | 订阅 `session.status` / `session.idle` / `message.updated` / `session.error` / `session.compacted` / `session.updated` —— **自动继续的总入口** |
| `command.execute.before` | 接管 `/goal` 命令 |
| `chat.message` / `chat.params` | 记忆发起代理/模型/变体，用于续作 |
| `tool.execute.before` | 控制命令上报轮次禁工具 |
| `experimental.compaction.*` | 压缩时注入目标摘要、禁用竞态自动继续 |
| `tool` | 注册 `goal_set/status/...` 模型工具 |
| `config` | 注册 `goal` / `goal-verify` 原生代理 |

### 1.3 自动继续的核心逻辑（关键决策）
- **仅由 `session.idle` 事件驱动**：会话一旦 idle，插件读取最新助手轮次，
  若未 `[goal:complete]`/`[goal:blocked]` 且未超限，则发送一条含剩余预算的**续作提示**。
- 续作前有去重/冷却/状态复核（防重复、防覆盖用户输入）。
- **无进展/无工具调用启发：仅在全话 idle 后评估**，且——
  **`reasoning` 仅 token 的轮次被明确排除在"停滞"之外**（见 `latestHasThinkingTokens`），
  以免误判思考型模型。

### 1.4 边界与局限（核心结论）
1. **被动、事件驱动**：插件只能对主机发出的事件作出反应；它没有独立时钟看门狗。
2. **thinking 卡死不可见**：模型陷入无限思考循环时——
   - 非 idle → 不触发 `session.idle` → 不自动继续；
   - 持续吐 reasoning → 被 `latestHasThinkingTokens` 排除 → 不判停滞；
   - 结果：引擎"永远等待"，无法纠正。
3. **与受监督者同进程**：插件寄宿在 opencode 进程内，若该进程/流被占用，插件自身的
   事件循环也可能被拖累，无法做可靠的独立心跳。
4. **结论**：**goal-plugin 在"会话内自主推进"上设计合理、合格；但它是"会话内层"，**
   **不具备"会话外、进程外、元层"的纠正能力。** 局限性是结构性的，不是补丁能解决的。

---

## 二、opencode 插件平台能力边界

opencode 通过插件钩子 + 生成的 SDK 客户端暴露能力，但**全部是"被宿主调用"的响应式接口**：

- 可：订阅事件、注入系统提示、改写命令/消息、注册工具、调用 `client.session.{create,abort,message,...}`。
- **不可**：没有独立于宿主事件循环的定时器契约；无法在"模型卡死、无事件"时自主唤醒；
  无法安全地中断一个正在 thinking 的轮次并原地续跑（abort 会丢掉该轮）。

因此，**插件的合理定位是"会话内执行员"，而"元监管"必须由进程外的独立监督者承担**。

---

## 三、元层（Meta-Layer）设计

### 3.1 原则
1. **监督者与受监督者分离**：元层独立进程/容器，拥有自己的时钟，能"杀死并重启"worker。
2. **把 worker 当黑盒**：worker 可被整体中止/重启（docker restart），其状态落在磁盘
   （goal-plugin 持久化 + 任务控制文档），重启后从磁盘恢复。
3. **纠正阶梯化**：从"轻提示"到"重恢复"，逐级升级，避免误伤。
4. **自我改善闭环**：每次运行后做"元复盘"，把经验写回策略文件，形成自我改进。

### 3.2 组件
```
[meta-supervisor 容器]  ← 独立看门狗 + 控制循环
 ├─ 看门狗时钟（独立心跳）        → 进程级 / 会话级 / 轮次级
 ├─ opencode API 客户端           → create/abort/message/event/health
 ├─ 纠正策略引擎                  → 分级纠正 + 阈值(free→deepseek 回退等)
 ├─ 元复盘 worker                 → 用模型会话读运行账本，产出改进建议
 ├─ 运行账本 / 指标存储            → 跨运行聚合（全局分析）
 └─ 策略文件(JSON)                → 自我改善的落点（受限自改）
        │ 控制
        ▼
[opencode-autopilot 容器]     ← opencode serve + goal-plugin + skills + reviewer
        （真正干活的工作者）
```

### 3.3 看门狗三级心跳（对应"thinking 卡死"检测）
| 层级 | 信号 | 判据 | 动作 |
|---|---|---|---|
| 进程级 | `/global/health` 轮询 + docker 进程 | 连续 N 次无响应 | 重启 worker 容器 |
| 会话级 | SSE `/event` 流 + `/session/status` | 非 idle 但长时间无**任何**事件 | 疑似挂起 → abort+重试 |
| 轮次级 | 事件流中 reasoning/工具/文字 | 单轮超 T 秒仅 reasoning、无工具调用、无文字收尾 | 判定"思考卡死" → abort+重试 |

> 关键：轮次级刻意**不**沿用 goal-plugin 的"reasoning 即非停滞"规则，而是
> 用**独立时钟**判"思考时间过长"。这正是元层补上的盲区。

### 3.4 纠正阶梯（逐级升级）
1. **L1 轻提示**：若会话 idle 但无进展 → 发送"继续/复盘"续作（优先级低于 abort）。
2. **L2 中止当轮**：`POST /session/:id/abort` 中止卡死轮次 → 触发 goal-plugin resume。
3. **L3 换模型**：free flash 失败/超时 → 切换到 `deepseek-api/deepseek-v4-flash` 重试。
4. **L4 重启进程**：`docker restart` worker → 从磁盘恢复目标。
5. **L5 人工升级**：仍失败 → 通知 + 停止，绝不无限重试。

### 3.5 自我改善（元复盘）
- 运行结束后，元层把 `run ledger`（事件时间线、纠正动作、耗时、费用）交给一个
  **独立模型会话**做复盘，输出结构化建议（如"reasoning 超 60s 无工具即判卡死"）。
- 建议经**护栏校验**（阈值界限、类型、不越权）后写回策略文件，供下次运行生效。
- 这是"受限的自我修改"：只改策略阈值，不改代码/不越权。

### 3.6 全局分析
- 跨运行聚合：各模型卡死率、纠正动作命中率、平均轮次/时长/费用、任务类型与停滞的相关性。
- 用于发现系统性问题（如"某模型反复挂起，应默认走官方 API"）。

### 3.7 元流程分析
- 元层用 `self-reflection` skill + 一个"流程审阅"代理，评估**任务控制文档/计划本身是否健全**：
  是否该重规划、是否该分解、是否该升级外部依赖。不只盯"任务做没做"，更盯"做任务的过程对不对"。

---

## 四、落地路径（Docker）
1. 保留现有 `opencode-autopilot` 容器作为 worker（已有 goal-plugin + skills + reviewer）。
2. 新建 `oc-meta`（或就在宿主/独立容器）运行升级版 supervisitor：
   - 现有 `supervisor.py` 扩为三级看门狗 + 纠正阶梯 + 策略文件。
   - 新增 `meta-review`（调用模型会话做复盘）与 `run-ledger` 存储。
3. 策略文件挂载共享，便于人工查看/微调。
4. 先做一次"人工注入 thinking 卡死"的故障演练，验证 L2/L3 能接管并恢复。

---

## 五、结论
- **goal-plugin = 优秀但"会话内"**：擅长自主推进，但结构上无法做元纠正。
- **本方案 = 进程外元层**：以独立时钟 + 分级纠正 + 自我改善闭环，补齐"thinking 卡死"
  等内嵌插件盲区，且把"自己都能挂"的恢复能力（重启/换模型/回退）放到进程外。
- 巧合的是，此前已选的"独立 supervisor.py + 容器隔离"架构，本就接近这个正确形态，
  只需按本文扩展为"三级看门狗 + 纠正策略 + 元复盘"。

> v0.2 修正：§五 的"内嵌插件盲区"表述需要限缩——插件可用定时器，"thinking 卡死盲区"
> 实为 goal-plugin 的**设计选择** + supervisor.py 的**指纹盲区**（见 §6.1）。

---

## 六、研究修正与 M0 落地（2026-08-03）

### 6.1 源码调研修正（相对 §一/§二 的表述）

- **插件平台并非"无独立时钟"**：插件寄宿在 Bun 进程，可自由 `setTimeout/setInterval`
  （goal-plugin 自身就用：wait 辅助、审计超时 goal-plugin.js:1965/3224）。"进程内定时器"
  的局限在于**独立性**（宿主挂它也挂），而非能力缺失。§1.4/§二 中"无独立时钟契约"表述应修正为
  "无**进程外独立**时钟，可靠性受限"。
- **opencode 内建超时（全是传输层，非 thinking 语义）**：
  - `provider.options.timeout`（默认 300_000ms）：单次 LLM 请求硬上限，`AbortSignal.timeout`
    并入 fetch（provider.ts:1754）；abort 后该轮上下文丢失（prompt.ts:1205 标记 Aborted）。
  - `provider.options.chunkTimeout`（默认 30_000ms）：SSE 两次 chunk 间隔超时，仅兜"完全静默"
    （provider.ts:37-83 wrapSSE）。模型持续吐 reasoning chunk 时不触发。
  - `headerTimeout`（默认 300s，openai）：首字节超时。
  - `agent.steps`（maxSteps）：步数上限，非时间。
- **thinking 盲区是"设计选择 + 指纹盲区"，双保险失效**：
  - goal-plugin：`latestHasThinkingTokens` 把 reasoning-only 轮次排除出 noProgress 停滞判定
    （goal-plugin.js:4539-4554）——主动豁免。
  - supervisor.py T3：`message_fingerprint` 把 reasoning 文本长度算进指纹（supervisor.py:61-79）
    ——被动盲区。thinking 循环时指纹持续变化，永不判停滞。
  - goal-plugin 的 `maxDurationMs/maxTurns/maxTokens` 仅在 idle 处理器检查（`stopReason`
    仅 goal-plugin.js:4481 一处调用）→ thinking 卡死（永不 idle）时这些预算也不触发。
- **观测面确认**：thinking 期间每次 `reasoning-delta` 触发 `message.part.updated` 事件
  （processor.ts:294-306 → session.updatePart → PartUpdated），进程内插件可实时观测；
  `session.status` 仅 `idle/busy/retry`，无 thinking 态（session-status-event.ts）。

### 6.2 M0 落地设计：双层守护（进程内 + 进程外）

```
[opencode-autopilot 容器]
  ├─ stall-watchdog 插件（进程内，第一道防线）
  │    · 事件级跟踪 reasoning-delta / text / tool
  │    · busy + 仅思考 > thinkingStallSec  → abort  → goal-plugin idle 恢复
  │    · busy + 无事件 > turnStallSec       → abort
  │    · 只观测 + abort，不注入提示不改目标；写 ledger
  └─ goal-plugin（会话内推进，负责 idle 恢复/预算/暂停）

[宿主 supervisor.py]（第二道防线，独立进程 + docker 控制权）
  ├─ T1 进程健康 + L4 docker restart
  ├─ T2 会话级停滞（minute 级）
  ├─ L3 模型回退 / L5 人工升级 / 期限强制
  └─ 消费 ledger，作为运行审计与未来自我改善数据源
```

分工：**插件测得到（秒级），脚本兜得住（独立性）**。二者阈值独立配置（`thinkingStallSec`
插件侧建议 60-120s；脚本侧 `turn_stall_sec`/`session_stall_sec` 保持分钟级）。

### 6.3 已归档调研
详见 `RESEARCH-thinking-timeout.md`（本轮网络+源码调研结论与证据链）。

### 6.4 元分析：顶层监控的"智能 + 确定性门"（supervisor v2，M0）

对应 §5 自我改善/元流程分析与 PLANNING §2 的 L1 调度器智能面，M0 以最简形态落地：

```
[top-level supervisor (host)]
  当 周期到 / 插件 gave_up / 阶梯触发 时:
   1. 收集：目标 + 当前时间 + 期限 + 会话状态 + 近期消息[带时间戳] + 近期账本事件
   2. 喂模型（opencode/deepseek-v4-flash-free，借用 opencode API；
       回退 deepseek-api 直连，密钥从 opencode 全局配置读取）
   3. 模型必须返回严格 JSON：{verdict, confidence, recommended_action, reason, evidence}
   4. 确定性门 _gate：verdict∈{normal,stalled,looping,blocked,error,escalate}
      action∈{none,nudge,abort,fallback_model,restart,human} 且 confidence∈[0,1]
      → 拒绝不合规输出（防模型乱来）
   5. 门内 action 映射到既定阶梯：abort(L2)/fallback_model(L3)/restart(L4)/human(L5)
```

设计要点：
- **智能负责"判未知"**：确定性看门狗判不了"模型陷入未知死循环"时，由模型结合时间戳/期限/消息流判 `looping/stalled`。
- **确定性负责"控"**：输出必须落白名单；违规即拒；动作由 supervisor 阶梯执行，模型不直接调 docker/API。
- 这正是未来"上帝对话框"中 L1 调度器 + 有界自省 + 确定性门的雏形（PLANNING §3 原则④、§4.5）。
- 已验证：循环场景→`looping/abort`(0.97)；时间戳过期+busy→`stalled/abort`(0.95)；端到端模型回退→complete。