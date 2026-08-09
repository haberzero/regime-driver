# 会话交接文档（HANDOVER）

> 供新工作区开启的新 session 读取，完整了解本项目背景、已做成果、当前状态与下一步。
> 新会话请先读本文件 + `PLANNING.md` + `docs/DESIGN.md`。

---

## 1. 项目一句话

在 Docker 里构建"可多人值守自主推进的 opencode 工作体系"，并进一步演进为**可自我修改、含反循环保证的元系统（上帝对话框）**。

## 2. 用户目标（原话要点）

- 驱动 opencode 自主工作，直到目标完成或到定时时间。
- 周期监控：检查工作是否暂停、检查任务控制文档/清单。
- 用 skill 做回顾、质量把控、代码核查；流程固定化、可控、可自反馈。
- 在 Docker 容器里运行。
- 痛点：opencode 内嵌插件无法纠正"元错误"（如 thinking 卡死浪费一晚），需进程外元层具备元纠正/自我改善/全局分析/元流程分析能力。

## 3. 环境与授权

- 主机：Linux，用户 `haber`，内存/GPU 充足。Docker 29.7.0。
- **docker 权限**：`haber` 已在 docker 组，但本 shell 是旧组，需用 `sg docker -c '...'` 包装 docker 命令。
- **网络**：Docker Hub 被墙 → 用镜像 `docker.m.daocloud.io` 拉基础镜像；npm 用 `registry.npmmirror.com`。
- **模型授权**：仅允许用 `opencode/deepseek-v4-flash-free`（主）+ `deepseek-api/deepseek-v4-flash`（回退）；**token plan 等一律不可用**。
- opencode 版本：1.18.11（镜像 `opencode-mvp:1.18.11`）。

### 3.x 自主运行配置（下游会话必须遵守）

- **禁 push**：除非明确授权，禁止 `git push`；只本地 commit。
- **破坏性重构授权**：符合一般工程/架构原则且经分析确实优于既有设计，允许破坏性重构（用户多次指示"彻底重构，不用关心兼容"）。
- **自主推进偏好**：偏向无人值守，最大限度自我决定；只有确实无法决定才上报。日志纪律："只记录，不断决"。
- **上报阈值**：`blocked` / `human_escalate` / 架构级方向调整 → 上报；审查发现的 blocker 必须修复后才能标记完成。
- **工作流**：每任务走 code-workflow + 质量门 + 全量测试零回归（`conda run -n regime-driver python -m pytest -q`）。

**Goal 模板（可直接复制）**：
```
【regime-driver · 开发模式】主任务：继续推进 regime-driver 系统。
一、主线任务（按序）：<从候选清单选一个>（内容+验收标准）→ 下一个候选 ...
   每完成一个任务用描述性 commit（说明+验证计数），同步更新任务控制文档，然后自动接续下一任务。
二、自主推进偏好（最高优先）：无人值守，最大限度自我裁定与自我质询分析并尽可能推进，
   只有穷尽自主手段后仍无法决定才形成阻塞；上报阈值统一为"先穷尽自主手段"。
三、交付纪律：本地 commit；禁止 push（硬原则）——除非明确授权。
四、工作流：每任务走 code-workflow + 质量门 + 全量测试零回归。
五、停止条件：先穷尽自主手段，仅当确实无法自主决定才停止并记录 blocker；硬性定时到达即停止并汇报。
```

## 4. 已完成的成果（全部经测试）

### 4.1 Docker 镜像
- `opencode-mvp:1.18.11`：Ubuntu 24.04 + Node 22 + opencode-ai@1.18.11 + Python 3.12 + git + curl。
- 入口 `opencode web --hostname 0.0.0.0 --port 4096`（`OPENCODE_PORT` 可覆盖）。

### 4.2 容器 opencode-autopilot（执行面，运行中）
- 端口 `0.0.0.0:4096->4096`，`--restart unless-stopped`。
- 挂载：
  - `~/.config/opencode` → `/root/.config/opencode`（双向同步，含 skills/agents）
  - `~/.local/share/opencode/auth.json` → 容器凭据
  - `/home/haber/oc-meta/workspaces/opencode-autopilot` → `/root/ws`（工作区）
  - `/home/haber/oc-meta/ops` → `/root/control`（监督器+策略）
- 工作区 `opencode.json` 激活 goal-plugin + goal 命令。
- 访问：`http://192.168.1.3:4096`（web 界面）。

### 4.3 配置注入（全局 `~/.config/opencode/`）
- 3 个 skill：`code-review`、`quality-gate`、`self-reflection`（SKILL.md，frontmatter 规范）。
- 1 个 agent：`reviewer.md`（只读评审，`edit/write: deny`）。
- 注意：这些是**全局**配置，对宿主机所有 opencode 会话生效。

### 4.4 元层监督器（`/home/haber/oc-meta/ops/supervisor.py`）
- **三层看门狗**：T1 进程级(health)、T2 会话级(无事件)、T3 轮次级(消息指纹稳定)。
- **纠正阶梯**：L1 轻提示 → L2 abort → L3 换模型 → L4 重启容器 → L5 人工升级，`max_retries` 兜底。
- **策略文件** `policy.json`（模型/回退/阈值/期限/重试全可配）。
- **运行账本** `run-ledger.jsonl`（结构化事件，自我改善数据源）。
- **meta_review**（可选，默认关）：读账本→模型会话→策略建议→护栏校验写回。
- stdlib only，可在容器内运行。
- **已修 bug**：`/session/:id/message` 返回 `{info,parts}`，解析须用 `info.role`/`parts`。

### 4.5 验证结果（3 条路径全过）
1. 完成路径：`start→session_created→complete→end(attempts=0)` ✅
2. 模型回退 L3：坏主模型→`goal_send_failed`→`escalate`→切 `deepseek-api/deepseek-v4-flash`→`complete` ✅
3. 停滞检测 T3/T2：逻辑与轮询循环共用，正常快任务无误报 ✅

### 4.6 设计文档
- `/home/haber/oc-meta/docs/DESIGN.md`：goal-plugin 源码级分析 + 元层设计。
  - 关键结论：goal-plugin 是**事件驱动**、无独立定时器；`latestHasThinkingTokens` 把 reasoning 排除在停滞判定外 → **thinking 卡死盲区**（本次痛点根因）。元层必须进程外、带独立时钟。
  - v0.2 修正：插件可用定时器；thinking 盲区实为 goal-plugin 设计选择 + supervisor T3 指纹盲区（详见 `RESEARCH-thinking-timeout.md` 与 DESIGN §6）。

### 4.7 stall-watchdog 插件（M0，`ops/stall-watchdog.js`，已部署运行）
- **定位**：进程内第一道防线，补 goal-plugin 与 supervisor.py 都测不到的"只思考不出活"。
- **机制**：`message.part.updated`（part 开始/结束时带类型）→ 学类型；`message.part.delta`（流式增量，无类型）→ 查类型分类。reasoning=活动无产出，text/tool=产出（重置时钟）。
- **两个判定**：busy + 仅思考 > `thinkingStallSec`(120s 测试期) → thinking 卡死；busy + 无事件 > `turnStallSec`(300s) → 静默挂起。
- **恢复**：abort 后 goal-plugin 把 abort 当"用户中断"会暂停目标 → watchdog 主动发 `/goal resume` 恢复；带**时间窗连续计数**（45min 内 >3 次 → `watchdog_gave_up`，abort 停流但不再 resume，留暂停目标给 supervisor）。
- **可配**：`thinkingStallSec/turnStallSec/pollSec/abortCooldownMs/maxConsecutiveAborts/giveUpWindowMs/resumeDelayMs/ledgerPath/enabled`。
- **已验证**：单元测试 8 项 + 故障注入全循环（stall→abort→resume→stall(2)→…→give_up，consecutive 1→4）。
- 文件挂载：`/home/haber/oc-meta/ops/stall-watchdog.js` → 容器 `/root/control/stall-watchdog.js`；`opencode.json` 以 `["file:///root/control/stall-watchdog.js", {…}]` 注册。

### 4.8 supervisor v2 宿主侧顶层监控（`ops/supervisor.py` + `ops/oc-run.sh`，已实现）- **运行位置**：宿主（`oc-run.sh` 用 `sg docker -c` + `setsid` 启动），拥有独立时钟 + docker 控制权（L4 restart 真正生效）。
- **三层看门狗**：T1 进程健康（/global/health + docker）→ L4 重启；T2 会话级（busy 但无新消息 > `session_stall_sec`）→ abort；**T3 轮次级已移交 stall-watchdog 插件**（插件写 ledger 事件）。
- **插件账本监听**：检测当前目标会话的 `watchdog_gave_up` → `plugin_gave_up_detected` → 交元分析。
- **元分析（智能 + 确定性门）**：周期（`meta_analyze_every_min`）或异常时，把**近期消息+时间戳** + 目标 + 期限 + 会话状态喂给 `opencode/deepseek-v4-flash-free`（opencode API 借用；回退 `deepseek-api/deepseek-v4-flash` 直连，密钥从 opencode 全局配置读取，不复制密钥）。
  - 模型输出严格 JSON：`{verdict, confidence, recommended_action, reason, evidence}`。
  - **确定性门** `_gate`：verdict/action 必须在白名单、confidence∈[0,1]，否则拒绝。
  - action → 阶梯：abort / fallback_model(L3) / restart(L4) / human(L5)。
- **启动入口**：`oc-run.sh '<goal>' [deadline_min]`（policy/ledger 可用环境变量覆盖）。
- **验证**：宿主跑真实目标完成 ✅；元分析两场景（循环→looping/abort、时间戳过期→stalled/abort）✅；**端到端**（stall 模型卡死→插件 give_up→supervisor 元分析判定 looping→回退真实模型→complete，attempts=1）✅；**docker stop→T1→L4 重启→恢复** ✅；**模型故障→L3 回退** ✅。
- **代码审查后硬化（2026-08-03）**：
  - `send_goal` 改异步（worker 线程），否则容器中途死亡时主循环进不了 T1 → 不重启直接 L5。`goal_fail` 共享标志让轮询循环感知目标发送失败并 abort 旧会话防重复执行。
  - 元分析改异步线程（`meta_dispatch`），不再冻结轮询循环（T1/T2/期限始终生效）；结果经 `meta_results` 消费。
  - 确定性门强化：per-action 置信度下限（restart/human≥0.75、abort/fallback≥0.5）+ verdict↔action 一致性白名单。
  - action 真正执行：restart(L4+wait_healthy)/human(终端 L5)/abort/stuck/fallback/nudge(L1 goal resume)。
  - 每轮尝试独立时间片（总预算÷(max_retries+1)，下限 2min），防主模型耗尽预算饿死 L3 回退。
  - meta 会话 try/finally 清理；用 POST 返回体取文本（修空读竞态）；ledger 行缓冲。
  - 完成/阻塞检测收紧为"最新助手消息末行精确匹配"（防误判）。
  - `oc-run.sh` 注入防护：goal 走 `--goal-file` + 全程 `printf %q`（审查发现的 blocker）。
  - stall-watchdog：giveup 改为**粘性**（黑名单直至新轮次）；abort 加超时竞态防挂起；新增 dispose 钩子；未知 status 一律清态。
- **已知限制/后续**：L1 空闲暂停目标续作仅靠 nudge(goal resume)，无独立 idle 检测；插件对"错过 busy 事件导致 idle 会话误建 busy 态"仍是理论边界；周期 code-review 未并入。**SSE 静默挂起**（fake 端点接受连接但不发 chunk）：实测 chunkTimeout 未按预期触发，静默挂起由**每轮尝试时间片兜底**（有界，随后 L3 回退完成）——已确认可恢复但非快速路径；`send_goal` worker 已加 `_resp_has_error` 检测响应中的 `MessageAbortedError` 使目标发送失败能被识别。生产每轮时间片默认 450s（deadline 30min÷4），静默挂起最多浪费 7.5min 后回退。

### 4.9 oc-task 任务接管接口 + git 管理（2026-08-03）

- **任务模型**：每任务 = 一个独立 supervisor 进程 + `ops/tasks/<id>.json` 记录（含 pid/out/summary）。无 daemon、无 systemd、不污染宿主——可控、可停、可清。
- **`oc-task.py` CLI**（人类与 opencode 共用）：`submit/list/status/stop/logs/clean` + 可选只读网页 `web start|stop|status`（http://127.0.0.1:8721）。
  - `submit` 把 goal 写临时文件经 `--goal-file` 传入（注入安全）；`--label-prefix <task-id>` 打标会话便于 `stop` 精确定位；`--summary-file` 落机器可读结果；`--pidfile` 记真实 python pid（supervisor 侧 SIGTERM 时先 abort 当前会话再退出）。
- **git 管理**：`/home/haber/oc-meta` 已 `git init` + 多次提交。`.gitignore` 排除账本/日志/web/pid/任务运行态/`__pycache__`；密钥零入库（deepseek 密钥只从 opencode 全局配置读取）。
- **interface 供你接手**：直接 `python3 ops/oc-task.py submit "<工程任务>"` 即可跑真实工程任务；或先 `web start` 在浏览器盯状态。

### 4.10 本会话成果（2026-08-05~06，分支 `autonomous-2026-08-05`）

- **P1 排查并修复 E2E 卡顿**：新增 `ops/probe_node_timing.py`（全流程节点耗时剖析）+ `ops/e2e_debug.py`（逐操作计时）+ `ops/probe_judge_stall.py`（并发观察 reasoning/output）。**根因 = 发派线程池饱和**：streaming `POST /message` 晚于 `message.completed`/`[WORK_DONE]` 返回，workflow 提前 advance 发下一 node，前 node POST 仍占线程 → 2 个 trailing POST 占满 `max_workers=2` → judge 发派永久排队 → 宪法误判 stall。修复：`workflow._dispatch` await 前一 POST future（`_await_prior_dispatch`，保持 STOP 响应）。真实 E2E 两次 COMPLETE；judge 长推理 21-60s 确认为长推理非永久卡。
- **P1 mock 机制**：`src/regime_driver/testing/mock_client.py`（MockClient/MockRule，同接口 drop-in，默认 reviewer advance + developer [WORK_DONE]，规则 `(agent,node)` 二段匹配，delay/stall/error 故障注入，消息累积非替换）。`ops/mock_feasibility.py` 5/5 离线通过。设计见 `docs/DESIGN-mock.md`。
- **上帝对话框 MVP**：`app/god_dialog.py`（GodDialogUnit 对等状态机单元，role=human，订阅总线实时监控 + 命令路由 status/monitor/start/inspect/watch/talk/design/config/help + 自由文本→LLM worker 线程非阻塞解释 + 权限门控默认只读）。`regime dialog` CLI + `ops/god_dialog.py` 演示。设计/可行性定案见 `docs/DESIGN-god-dialog.md`（结论：**对话框应在状态机体系内**）。
- **测试基线**：192 单测全绿（含崩坏回归：`test_dispatch_serializes_prior_post`、`test_judge_waits_for_new_reply_not_stale`、`test_god_dialog.py` 等）。

## 5. 关键决策与踩坑记录

- **插件不能做周期/定时唤醒**：opencode 插件 hook 是事件驱动，无独立时钟契约 → 周期检测必须靠独立进程脚本。
- **控制面应是确定性脚本，而非又一个 agent**：agent 守不住固定流程；固定流程须用具体脚本硬约束。
- **"对话脚本"= 脚本是对象，对话是操控它的界面**（用户命名：上帝对话框）。用户要的是可对话、可自我修改、含反循环保证的元系统。
- **后台进程存活**：bash 工具每次调用结束会清掉后台进程，长驻服务须用独立进程/容器（`setsid`/docker 常驻）。
- **docker 权限**：`sg docker -c` 包装。

## 6. 当前运行状态

- **架构：对等多状态机网络**（宪法=无智能状态机+根不变量运行时强制 I1/I2/I3）+ **进程外 `supervisor`**（T1/T2/deadline/纠正阶梯，收编 M0）+ **`task` 注册表** + **`Reporter` 报告总线** + god 双路。旧 `app/telemetry.py`/`monitor.py`/`meta_analyzer.py`/`segment_runner.py` 已删除；旧 `ops/supervisor.py`/`oc-task.py`/`oc-run.sh`/`stall-watchdog.js` 已收编删除。
- **`opencode-worker` 容器**：端口 4097，`serve --pure` 无插件执行器，镜像 `opencode-worker:1.18.11`。
- **`opencode-god` 容器（新增，A 路验证窗）**：端口 4098，host 网络，装 regime-driver + god.md + regime-god 插件，非 `--pure`。见 `docs/howto/god-window.md`。
- **测试基线**：255 passed（+2 skip E2E 门控）。真实 worker E2E 已打通（REGIME_E2E=1）+ god A 路 HTTP 驱动打通。死代码守卫 + CLI 命令级测试已加。
- **CLI 契约**：`regime` 命令集 `run/run-many/validate --deep/preflight/gate/status/sessions/session/events/dialog/job/report/task/supervisor` 全部 `--json` + 权限门禁（`--perm`，配置 ceiling 不可自提权）。
- **技术债治理完成**：G1–G14 全清（`docs/TECH_DEBT.md`）；权限/保障默认强制；文档单点真理收口。
- 工作区已清理测试产物。

## 7. 主目录污染清单（已迁移/清理完成）

| 路径 | 处置 | 状态 |
|---|---|---|
| `oc-control/` | → `oc-meta/ops/` + `oc-meta/docs/DESIGN.md` | ✅ 已迁 |
| `oc-workspaces/` | → `oc-meta/workspaces/opencode-autopilot` | ✅ 已迁 |
| `work/` | 删除 | ✅ 已删 |
| `~/.cache/opencode-test/` | 删除 | ✅ 已删 |
| `~/.config/opencode/skills|agents` | 保留全局（容器同步需要）+ 复制参考副本到 `oc-meta/skills|agents`；归属决策留待下个 session | ✅ 已复制 |

迁移后 `oc-control`、`oc-workspaces`、`work` 均已从主目录移除，唯一残留为规范化后的 `/home/haber/oc-meta/`。

## 8. 下一步（下一 session 主线任务）

> **当前主线（唯一指针，2026-08-08）**：完成技术债治理（G1–G14 全清）+ 测试架构闭环
> （E2E / god 容器 / A 路打通）后，**下一 session 主攻"运行可信度 + 易用性"**：
> 见下方"下一 session 主线任务（优先级表）"。

### 当前状态速览（2026-08-08）

- **测试基线 299 passed（+6 skip）**，分支 `autonomous-2026-08-05`，干净工作树。
- **容器**：`opencode-god`（4098，A 路验证窗，host 网络）、`opencode-worker`（4097，默认执行器）、
  以及**每工作区一个的 `opencode-worker-<ws>` 实例**（`regime worker` 管理，物理隔离）、
  `opencode-autopilot`（4096，web，M0 遗产已退役监督）。
- **架构**：对等多状态机网络（宪法根不变量）+ 进程外 `supervisor`（收编 M0，含智能元分析）+
  `task` 注册表 + `Reporter` 报告总线 + god 双路 + **`drive` 一键自驱动栈** +
  **`WorkerPool` 多实例工作区隔离**（每工作区一个 opencode 实例，角色用 session）+
  **`Fleet` 并发隔离舰队** + **`chaos` 故障注入/恢复演练**。
- **一键起栈**：`ops/up.sh`（worker/god 一键构建+拉起+等健康，sg fallback，--rebuild）。
- **技术债**：G1–G14 全清（`docs/TECH_DEBT.md`），无已知双通道/半接通死能力/双写真相。
- **测试架构**：`tests/test_e2e_worker.py`（REGIME_E2E 门控，含真实 drive/supervisor 无假停滞 +
  T1→L4 重启恢复 + 元分析真实模型）+ 死代码守卫 `test_deadcode.py`（扩 drive/god_dialog）+
  CLI 命令级测试 `test_cli.py`。

### 下一 session 主线任务（优先级表，我的判断）

| # | 任务 | 视角 | 说明 |
|---|---|---|---|
| ~~P0~~ | ~~一键自驱动入口~~ | ✅ 已完 | `regime drive <task>`（执行器+supervisor+reporter 一栈共享 journal + 受监管任务），见 `DESIGN-drive.md` |
| ~~P0~~ | ~~真实 E2E + supervisor 卡死恢复~~ | ✅ 已完 | 真实 drive/supervisor 无假停滞 + 真实 T1→L4 重启恢复 + 元分析接真实模型（`--meta`），见 `DESIGN-supervision.md` §6 |
| ~~P1~~ | ~~god 容器固化 + 一键起栈~~ | ✅ 已完 | `ops/up.sh` + 镜像固化（插件/agent/配置进镜像），见 `howto/god-window.md` |
| ~~P1~~ | ~~CI 接入真实 E2E~~ | ✅ 已完 | `ci.yml` e2e-real job（secret 门控），真实执行链成回归门槛 |
| ~~P2~~ | ~~测试金字塔/守卫扩展 + B 路 T8~~ | ✅ 已完 | 死代码守卫扩 drive/god_dialog；GodDialog `sessions/abort/reclaim`；**修权限 classify 洞**（drive/task/supervisor 原绕过写门禁） |
| ~~P2~~ | ~~worker 工作区物理隔离~~ | ✅ 已完 | 转"多 opencode 实例，每工作区一个"（用户指令）：`regime_driver.worker.WorkerPool` + `regime worker up/down/list/base` + `drive --workspace`；真实 E2E 隔离验证通过，见 `DESIGN-worker-isolation.md` |
| ~~P2~~ | ~~并发隔离舰队~~ | ✅ 已完 | `regime_driver.fleet.Fleet` + `regime drive-many --workspaces`：并行全栈 Drive 每工作区一实例，共享一 reporter；`DESIGN-fleet.md` |
| ~~P2~~ | ~~舰队控制面~~ | ✅ 已完 | `WorkerPool.max_instances`(env REGIME_WORKER_MAX_INSTANCES) + `regime worker prune`(回收无会话空闲实例) + GodDialog `fleet` 舰队视图 |
| ~~P2~~ | ~~混沌/故障演练~~ | ✅ 已完 | `regime_driver.chaos.FaultInjector` + `regime chaos list/inject/scenario`（worker-crash-recovery 真实恢复验证）；`DESIGN-chaos.md` |
| **P3** | 收敛测试内零散 FakeClient | 健康 | T6 已评估不转 MockClient（非 drop-in，防漂移）；如需统一另建轻量脚本化 fake |

> 若只做一件：选 **worker 工作区隔离**（已按用户指令以"多实例每工作区一个"完成，见 `DESIGN-worker-isolation.md`）。
> 建议：先按 `docs/DESIGN-drive.md`/`DESIGN-supervision.md`/`DESIGN-worker-isolation.md` 熟悉新 `drive`/`--meta`/`--workspace`。`main_loop` 死 flow 已于 2026-08-08 移除。

### 已完成主线（历史，参考）

- **P0#1/P0#2/P1#3/P1#4/P2#5** ✅：见本表上方（本轮 session 完成）。
- **T1/T2 A 路验证** ✅：经专用 god 容器 + HTTP 驱动打通；修 regime-god.js 三个真 bug。
- **T3/T4/T5/T7/T6** ✅：非阻塞作业、插件 job 工具、权限策略、文档同步、FakeClient 评估定案。
- **WORK_PLAN4** ✅：I1/I2 保障、E1 SSE 摄入+重连、R-A/R-B/R-C（Reporter 报告总线 + `regime report` 看板 + 模板 + 保留策略）。
- **技术债治理** ✅：G1–G14 全清（含 G6 M0 系统化收编、死代码守卫、静默兜底修复、权限强制、文档单点真理）。
- **测试架构** ✅：T-A E2E 系统化、T-B god 容器、T-C A 路打通、T-E 交接收口。

**历史里程碑**：M0–M4 ✅、架构 v2/v3/v4 ✅、对等多状态机重构 ✅、E2E 卡顿修复 ✅、mock ✅、WORK_PLAN1/2/3 ✅。

**待决技术项**：monkey 用 `RolePolicy(transition_mode=ROTATE)` 构造时 dataclass 字段默认值遮蔽类属性（测试已规避）。历时超时模型：`default_deadline_sec` + `global_deadline_sec`。

阅读顺序：`docs/README.md`（导航，先看）→ `DESIGN-regime-driver.md` → `ARCHITECTURE-regime-driver.md` → `ARCHITECTURE-v2.md` → `ARCHITECTURE-v3.md` → `ARCHITECTURE-v4.md` → `ARCHITECTURE-BOUNDARY.md` → `ARCHITECTURE-statechart-network.md`（最终架构）→ `DESIGN-mock.md` → `DESIGN-god-dialog.md` → `DESIGN-god-dialog-carrier.md`（载体决策）→ `GOD_DIALOG_OPERATOR.md`（操作手册）→ `docs/KNOWN_LIMITS.md`（边界）→ `docs/howto/`（实操）。**当前主线规划：`WORK_PLAN4.md`**（预检 + 事件链路 + 宏观汇报台账）。书写准则：`docs/WRITING_GUIDE.md`；文档治理：`skills/doc-governance/SKILL.md`。

**关键决策速记**：审查者常驻 session（只读不可跑命令，可要求开发者跑）；开发者 1 个 session（基础 AGENTS.md，不自查，段末 `[WORK_DONE]` 汇报，5 轮里程碑询问）；**角色是独立个体，靠交接单协作，审查者只读汇报单不读开发者记忆**；**session 自评驱动脑容量交接（40% 自评/70% 紧急），非机器人硬掐断**；**审查者流转时开发者 session 禁止切换（稳定锚点）**；交接文档 session 直接写工作区，载体文件系统 + Ledger 审计；策略可编程（Python+模板，参考策略预置）；JSON 契约与镜像自主决定；全局状态清单（开发者不可见）单独设计；**安全监控独立线程 + 确定性 abort 紧急停止**；**对等多状态机网络（宪法=无智能状态机+根不变量运行时强制）**；**上帝对话框双路：opencode 作载体（A 路）+ GodDialogUnit 程序化面（B 路），共用 CLI 契约**。

### 里程碑进度

| M | 内容 | 状态 |
|---|---|---|
| **M-1** | worker 镜像 `opencode-worker:1.18.11`（miniconda + 无插件 + reviewer 只读 agent） | ✅ **完成，容器运行中** |
| **M-2** | L1 骨架：正式工程包 `regime-driver`（src/ 布局 + 确定性门 + session 管理 + 5 轮检查 + `[WORK_DONE]` 段协议） | ✅ **完成，17 单测 + 端到端全绿** |
| **M-3** | 审查者接入：skill 注入 + 判定回路 + 硬规则 + 任务控制文档 | ✅ **完成，33 单测 + 端到端全绿** |
| **M-4 前置** | 安全监控与紧急停止（独立监控线程 + 死循环检测 + abort 上报） | ✅ **完成，45 单测 + 端到端全绿** |
| M-4 | 试跑真实工程任务 + 故障演练 | ✅ **完成（2026-08-05）：真实 worker 全流程 COMPLETE，119 单测** |

**待办（最新候选）**：① 收敛测试内零散 FakeClient 到 MockClient（T6 已评估不转，如需统一另建轻量脚本化 fake）；② P3 杂项：技术待决——monkey 用 `RolePolicy(transition_mode=ROTATE)` 构造时 dataclass 字段默认值遮蔽类属性（测试已用构造参数规避）。历时超时模型：`default_deadline_sec`（每节点）+ `global_deadline_sec`（整轮）。

## 9. 命令速查

```bash
# 环境
source ~/miniconda3/etc/profile.d/conda.sh

# 校验 / 预检（保障默认强制）
conda run -n regime-driver regime validate [--deep/--no-deep] [--skills-dir workflow-regime/skills] --json
conda run -n regime-driver regime preflight [--fault stall|delay] --json   # 离线试跑
conda run -n regime-driver regime gate '<verdict-json>'

# 运行（单跑/并发/异步，preflight 默认强制）
conda run -n regime-driver regime run "<任务>" --base http://127.0.0.1:4097 --reporter /tmp/rep.jsonl [--no-preflight]
conda run -n regime-driver regime run-many "t1" "t2" --base http://127.0.0.1:4097 --reporter /tmp/rep.jsonl
conda run -n regime-driver regime run "<任务>" --async --reporter /tmp/rep.jsonl   # 非阻塞
conda run -n regime-driver regime job list|status <id> --json

# 一键自驱动栈（P0#1: 执行器+supervisor+reporter 一栈, 受监管任务）
conda run -n regime-driver regime drive "<任务>" --base http://127.0.0.1:4097 \
  --container opencode-worker --deadline 1800 --reporter /tmp/rep.jsonl [--meta]
conda run -n regime-driver regime drive "<任务>" --async --container opencode-worker --reporter /tmp/rep.jsonl
conda run -n regime-driver regime task status <task-id>      # 跟踪受监管任务
conda run -n regime-driver regime task stop <task-id>        # 停止

# 报告总线（宏观看板 / 因果链 / 模板 / 保留）
conda run -n regime-driver regime report --journal /tmp/rep.jsonl [--wf id] [--tasks-dir] [--json]
conda run -n regime-driver regime report <object> --trace --journal /tmp/rep.jsonl
conda run -n regime-driver regime report --journal /tmp/rep.jsonl --template milestone|blocker|period|activity
conda run -n regime-driver regime report --journal /tmp/rep.jsonl --prune --max-records 500

# 会话 / 事件 / 上帝对话框
conda run -n regime-driver regime sessions|session <id> send|reply|events --ledger ... --json
conda run -n regime-driver regime dialog --live --base http://127.0.0.1:4097 --perm run

# 任务注册表（收编 oc-task）
conda run -n regime-driver regime task list|status|logs|stop|clean <task-id> [--json]

# 进程外监督（收编 supervisor；宿主独立时钟 + docker 控制）
conda run -n regime-driver regime supervisor --base http://127.0.0.1:4097 --session <id> --container opencode-worker --reporter /tmp/sup.jsonl [--meta] [--once]

# 一键起栈（P1#3: worker/god 容器构建+拉起+等健康）
ops/up.sh all          # worker+god
ops/up.sh god --rebuild   # 强制重建固化镜像再起

# 多 opencode 实例工作区隔离（P2: 每工作区一个实例, 无重复, 角色用session）
export REGIME_WORKSPACE_ROOT=~/oc-meta/workspaces   # 工作区根(默认)
export REGIME_WORKER_MAX_INSTANCES=8                # 可选: 舰队实例上限
conda run -n regime-driver regime worker up <ws>     # 起/复用工作区实例(不重复)
conda run -n regime-driver regime worker list        # 列实例+健康
conda run -n regime-driver regime worker base <ws>   # 工作区实例 base_url
conda run -n regime-driver regime worker down <ws>   # 停止并移除实例(含chown回宿主)
conda run -n regime-driver regime worker prune [--dry-run] [--max-instances N]  # 回收空闲实例/设上限
conda run -n regime-driver regime drive "<任务>" --workspace <ws> --container opencode-worker-<ws> --reporter /tmp/rep.jsonl   # 在隔离工作区跑整套栈

# 并发隔离舰队（P2: N个任务各自工作区并行全栈）
conda run -n regime-driver regime drive-many "t1" "t2" "t3" \
  --workspaces "wsA,wsB,wsC" --workers 2 --deadline 600 --reporter /tmp/fleet.jsonl

# 混沌/故障演练（P2）
conda run -n regime-driver regime chaos list                              # 场景列表
conda run -n regime-driver regime chaos inject kill <ws>                  # 注入单故障
conda run -n regime-driver regime chaos scenario worker-crash-recovery <ws>  # 崩溃恢复场景

# 单测 / E2E（E2E 门控: REGIME_E2E=1 且 worker 健康）
conda run -n regime-driver python -m pytest
REGIME_E2E=1 conda run -n regime-driver python -m pytest tests/test_e2e_worker.py -q

# 容器
sg docker -c 'docker ps --format "{{.Names}} {{.Status}}"'
sg docker -c 'docker restart opencode-worker'
sg docker -c 'docker build -f docker/Dockerfile.worker -t opencode-worker:1.18.11 .'

# 上帝对话框 A 路验证窗（opencode-god 容器, host 网络, 4098）— 见 docs/howto/god-window.md
sg docker -c 'docker build -f docker/Dockerfile.god -t opencode-god:1.18.11 .'
sg docker -c 'docker rm -f opencode-god; docker run -d --name opencode-god --network host -e DEEPSEEK_API_KEY="$(cat /tmp/dk.txt)" -e OPENCODE_PORT=4098 opencode-god:1.18.11'
curl -s http://127.0.0.1:4098/global/health

# 启动监督器（旧方式，容器内；现已被 oc-task 取代）
docker exec -d opencode-autopilot python3 /root/control/supervisor.py \
  --goal "<目标>" --policy /root/control/policy.json
```