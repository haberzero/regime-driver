# 会话交接文档（HANDOVER）

> 供新工作区开启的新 session 读取，完整了解本项目背景、已做成果、当前状态与下一步。
> 新会话请先读本文件 + `docs/README.md`（技术文档导航）；历史规划/任务档案见 `tasks_docs/`。

---

## 1. 项目一句话

在 Docker 里构建"可多人值守自主推进的 opencode 工作体系"，并进一步演进为**可自我修改、含反循环保证的元系统（控制对话框）**。

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
- **模型授权**：默认模型为 DeepSeek 官方 API `deepseek-api/deepseek-v4-flash`（密钥 `DEEPSEEK_API_KEY` 或 `~/.regime/keys/deepseek.key`）；`my-opencode-go/deepseek-v4-flash`（OpenCode Go）作回退。详见 `docs/guide/04_environment.md`。自检 `regime doctor`。
- opencode 版本：1.18.11（镜像 `opencode-mvp:1.18.11`）。

### 3.x 自主运行配置（下游会话必须遵守）

- **代码审查必须用 `general` task agent（只读、不改文件）；严禁使用 `reviewer` task agent。**
  用户硬性决定（同仓库根 `AGENTS.md`）。每完成里程碑/阶段即用 `general` 独立只读 review，
  修复其 blocker/warning 后方可标记完成并 commit。
- **push 已授权（2026-08-10 起）**：项目已公开上传 `https://github.com/haberzero/regime-driver`（`main`，
  SSH 认证），用户明确授权 push。默认远端 = `origin`（SSH）；当前工作分支 = `main`，
  `git push origin main:main` 即同步。push 会触发 GitHub Actions（CI 已绿）。
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

### 4.2 容器 opencode-autopilot（M0 遗产，**已退役删除 2026-08-12**）
> 该容器是 M0 时代（goal-plugin + stall-watchdog + supervisor.py 三件套）的执行面，已被
> `regime drive`（executor + supervisor + reporter 一栈）取代。**2026-08-12 交接清理时删除**，
> 工作区产物一并移除（root 权限残留由运维清理）。历史信息保留如下供参考。

### 4.3 配置注入（全局 `~/.config/opencode/`）
- 3 个 skill：`code-review`、`quality-gate`、`self-reflection`（SKILL.md，frontmatter 规范）。
- 1 个 agent：`reviewer.md`（只读评审，`edit/write: deny`）。
- 注意：这些是**全局**配置，对宿主机所有 opencode 会话生效。

> **历史遗留（M0 时代，已收编删除）**：§4.4–4.9 记录的是早期 M0 监督器/oc-task/stall-watchdog/
> oc-run.sh 的产物。这些脚本**均已退役删除**（见 §6：`ops/supervisor.py`、`oc-task.py`、`oc-run.sh`、
> `stall-watchdog.js` 已收编进 `regime_driver.supervisor`/`task`/CLI）。保留此处仅作历史与设计演变参考；
> 当前运行面请以 §6/§8 与 `regime supervisor`/`regime task`/`regime drive` 为准。

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
  - v0.2 修正：插件可用定时器；thinking 盲区实为 goal-plugin 设计选择 + supervisor T3 指纹盲区（详见 `docs/architecture/02_statechart_network.md`）。

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

- **P1 排查并修复 E2E 卡顿**：新增 `ops/probe_node_timing.py`（全流程节点耗时剖析）+ `ops/e2e_debug.py`（逐操作计时）+ `ops/probe_judge_stall.py`（并发观察 reasoning/output）。**根因 = 发派线程池饱和**：streaming `POST /message` 晚于 `message.completed`/`[WORK_DONE]` 返回，workflow 提前 advance 发下一 node，前 node POST 仍占线程 → 2 个 trailing POST 占满 `max_workers=2` → judge 发派永久排队 → 看门狗误判 stall。修复：`workflow._dispatch` await 前一 POST future（`_await_prior_dispatch`，保持 STOP 响应）。真实 E2E 两次 COMPLETE；judge 长推理 21-60s 确认为长推理非永久卡。
- **P1 mock 机制**：`src/regime_driver/testing/mock_client.py`（MockClient/MockRule，同接口 drop-in，默认 reviewer advance + developer [WORK_DONE]，规则 `(agent,node)` 二段匹配，delay/stall/error 故障注入，消息累积非替换）。`ops/mock_feasibility.py` 5/5 离线通过。设计见 `docs/subsystems/08_mock.md`。
- **控制对话框 MVP**：`app/dialog_control.py`（DialogControlUnit 对等状态机单元，role=human，订阅总线实时监控 + 命令路由 status/monitor/start/inspect/watch/talk/design/config/help + 自由文本→LLM worker 线程非阻塞解释 + 权限门控默认只读）。`regime dialog` CLI + `ops/dialog_control.py` 演示。设计/可行性定案见 `docs/subsystems/06_dialog_control.md`（结论：**对话框应在状态机体系内**）。
- **测试基线**：192 单测全绿（含崩坏回归：`test_dispatch_serializes_prior_post`、`test_judge_waits_for_new_reply_not_stale`、`test_dialog_control.py` 等）。

## 5. 关键决策与踩坑记录

- **插件不能做周期/定时唤醒**：opencode 插件 hook 是事件驱动，无独立时钟契约 → 周期检测必须靠独立进程脚本。
- **控制面应是确定性脚本，而非又一个 agent**：agent 守不住固定流程；固定流程须用具体脚本硬约束。
- **"对话脚本"= 脚本是对象，对话是操控它的界面**（用户命名：控制对话框）。用户要的是可对话、可自我修改、含反循环保证的元系统。
- **后台进程存活**：bash 工具每次调用结束会清掉后台进程，长驻服务须用独立进程/容器（`setsid`/docker 常驻）。
- **docker 权限**：`sg docker -c` 包装。

## 6. 当前运行状态

- **架构：对等多状态机网络**（看门狗=无智能状态机+根不变量运行时强制 I1/I2/I3）+ **进程外 `supervisor`**（T1/T2/deadline/纠正阶梯，收编 M0）+ **`task` 注册表** + **`Reporter` 报告总线** + 控制对话框双路。旧 `app/telemetry.py`/`monitor.py`/`meta_analyzer.py`/`segment_runner.py` 已删除；旧 `ops/supervisor.py`/`oc-task.py`/`oc-run.sh`/`stall-watchdog.js` 已收编删除。
- **`opencode-worker` 容器**：端口 4097，`serve --pure` 无插件执行器，镜像 `opencode-worker:1.18.11`。
- **`opencode-dialog-control` 容器（新增，A 路验证窗）**：端口 4098，host 网络，装 regime-driver + dialog-control.md + regime-dialog-control 插件，非 `--pure`。见 `docs/howto/dialog-control-window.md`。
- **测试基线**：255 passed（+2 skip E2E 门控）。真实 worker E2E 已打通（REGIME_E2E=1）+ 控制对话框 A 路 HTTP 驱动打通。死代码守卫 + CLI 命令级测试已加。
- **CLI 契约**：`regime` 命令集 `run/run-many/validate --deep/preflight/gate/status/sessions/session/events/dialog/job/report/task/supervisor` 全部 `--json` + 权限门禁（`--perm`，配置 ceiling 不可自提权）。
- **技术债治理完成**：G1–G14 全清（`TECH_DEBT.md`）；权限/保障默认强制；文档单点真理收口。
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
> （E2E / 控制对话框容器 / A 路打通）后，**下一 session 主攻"运行可信度 + 易用性"**：
> 见下方"下一 session 主线任务（优先级表）"。

### 当前状态速览（2026-08-12）

> **术语已整体改名（2026-08-12，用户拍板，全仓无遗漏）**：上帝对话框→**控制对话框**
> （GodDialogUnit→DialogControlUnit、god_dialog.py→dialog_control.py、opencode-god→
> opencode-dialog-control、regime-god.js→regime-dialog-control.js、god.md→dialog-control.md、
> `God>`→`Dialog>`、工作流 id 前缀 god-→dialog-、scaffold `--god`→`--assistants`）；
> 舰队→**并行任务**（Fleet→Parallel、fleet.py→parallel.py、dialog 命令 fleet→parallel）；
> 宪法→**安全看门狗**（ConstitutionUnit→WatchdogUnit、constitution_unit.py→watchdog_unit.py）。
> **载体/承载（carrier）恢复原样**（用户指示：该词使用正常，无需修改；07 文件为
> `07_dialog_control_carrier.md`，文档仍用"载体决策/对话载体/作载体"）。
> tasks_docs 历史档案保留旧词。活文件旧词残留 grep=0（经 general review 复核并清零）。

- **测试基线 413 collected（全绿，覆盖 72%）**，分支 `main`，干净工作树。
- **质量收益验证（✅ 2026-08-13 夜）**：12 个复杂工程任务套件（`ops/quality_tasks.py`）经
  `regime drive` 监督栈 2h/43 次运行——最后一轮 12/12 complete，宿主外部 pytest 12 任务全 0
  failed（239 断言），reviewer 每任务 2–4 次实质判定。报告 `tasks_docs/quality_report.md`。
  期间**发现并修复真实 bug**：`reviewer` agent `bash "*": ask` 在 headless 下被复杂任务逼着跑
  `pytest` 触发权限 ask 死锁（挂 600s）→ 改 `"*": deny` + 只读白名单（双源同步 + 打包副本 +
  运行容器）。
- **文档站完整重构（✅ 2026-08-12）**：MkDocs + Read the Docs 主题（`https://haberzero.github.io/regime-driver/`）。
  三层受众彻底分层：**用户指南**（控制对话框第一入口 → 快速开始 → 你能做什么 → 设计流程 → 安装/配置/
  并行任务）+ **参考**（查技术细节）+ **开发者指南**（架构/子系统/契约/治理）。agent 专用内容（skills /
  控制对话框助手 / workflow-regime 模板）完全隔离，不入站，由 `regime scaffold` 提供。
  - 首页以"元指令会遗忘"叙事切入（你给 opencode 的约束在多轮对话后会被遗忘 → regime-driver 把运行
    制度变成确定性流程 → 你仍只需对话）。
  - 框架展示细化：对话背后发生了什么（制度驱动规划 → 角色/节点出现 → 会话按角色分配 → 逐节点配合 →
    事件记录）；为什么 skill 不直接加载进对话框（上下文/专注度/结构性保证三重考量）。
  - worker 干净执行器 / dialog-control 带插件对话面的分层说明。
- **初学者读者视角文档批评 + 落地（✅ 2026-08-12）**：以普通读者视角通读全部对外文档产出批评报告
  （`tasks_docs/docs_reader_critique.md`），逐条核实代码后全面改进——guide 编号去重（03 双号→00-07）、
  reference/05 契约归位"参考"区、README 中英去 L0/L1/L2 代号与密钥段重复、去 stale 表述（DELETE 真删、
  CLI 契约已就绪、架构文档对齐实现）、概念去重（code_workflow 表 / worker-dialog-control 表收敛单一归属）、
  新增图解（index 系统全景图 / 审查判定闭环 / 监督纠正阶梯 / 事件链时间线 / 并行任务隔离图）。零回归、
  0 死链、general review 无 blocker。
- **长期耐久验证（WORK_PLAN6 I L1+L3 ✅，2026-08-12）**：2h 真实运行（7205s，38 drive）零崩溃/
  停滞/重启（ladder=0），资源线性有界增长（session 16→96、内存 +231MB/2h、journal 3.4MB），
  worker 全程健康。完成率 27/38（11 个 timeout 命中 600s deadline，根因=验证过度订阅单 worker，
  非系统缺陷）。报告 `tasks_docs/durability_report.md`；结果记入 KNOWN_LIMITS。
- **L2 资源治理（✅ 2026-08-12）**：`regime doctor` 增 "session hygiene" 检查（累积 session ≥
  `session_hygiene_threshold`(默认100) 警告清理/重建）；`regime drive` 增 `--prune-max-records/
  --prune-max-age`（收尾自动 journal 保留，best-effort）。**session 清理策略**：`sessions --cleanup`
  （可配置参考模型，`session_cleanup_policy`），已核实 opencode 1.18.11 DELETE /session 真正删除。
- **版本耦合护栏（✅ 2026-08-12）**：`OpenCodeClient.health_info/check_version`（major.minor 匹配，
  SUPPORTED_OPCODE=1.18.11）+ `regime doctor` "opencode version" 检查（漂移即警告）。
- **示例流程（✅ 2026-08-12）**：`src/regime_driver/data/examples/verify_then_report.json`
  （tool+route 分支示例，随 wheel 打包）。
- **e2e-real 已封存（用户决定，2026-08-11）**：GitHub 真实模型 E2E 长期不列入计划；CI 已移除
  `e2e-real` job；`tests/test_e2e_worker.py` 保留本地/手动可用（`REGIME_E2E=1`）。
- **默认模型 = DeepSeek 官方 API**：`deepseek-api/deepseek-v4-flash`（用户授权，实测 1.6s vs opencode-go 40s，
  快一个数量级）；`my-opencode-go/...`（OpenCode Go）作回退。主机+worker/dialog-control 全统一。key：
  `DEEPSEEK_API_KEY` 或 `~/.regime/keys/deepseek.key`。自检 `regime doctor`。
- **对外供给就绪（WORK_PLAN7 I–IV + V-3 ✅，2026-08-11）**：
  - **模板进包**：wheel 现含 `data/{skills,agents,dialog-control-assistants,docker}`（hatchling 自动纳入包内 data/）；
    纯 wheel 隔离安装下 `regime preflight --json` 实测 `ok:true, outcome:complete`（此前必败）。
    `DEFAULT_SKILLS_DIR` 已改为包内 `data/skills`（去源码树假设）。
  - **`regime scaffold`**：一键从包内模板生成 `~/.config/opencode/{agents,skills}`（+`--assistants` 助手；
    幂等/`--dry-run`/`--force`）；`regime doctor` 增"packaged templates"就绪检查。
  - **单一真源收敛**：根 `agents/`、`skills/` 副本删除；真源 = `docker/*-config/agents` +
    `workflow-regime/skills`；打包派生 = `src/regime_driver/data/`，CI 漂移守卫
    `test_packaged_templates_match_true_sources` + 同步脚本 `ops/sync_templates.py [--check]`。
  - V-1（GitHub Pages 已启用）/ V-2（PyPI，用户近期处理）。
- **控制对话框制度设计闭环（P0 主线）✅（2026-08-11）**：
  - `regime flow design <name> '<spec>'`：inline 注册新流程（无需文件），控制对话框设计制度主入口；
  - `regime status --deep`：一次拿全聚合态势（健康+会话+busy+流程+任务+reporter rollup）；
  - `regime run/drive --flow <name>`：按名执行注册流程（dialog-control 设计的流程可运行）；
  - **终止 judge 节点 gate 修复**：advance+null next_state 仅当 terminal 节点放行（此前"最终审查 judge
    流程永远无法完成"，preflight gate exhausted）；
  - 控制对话框插件新增 `regime_flow_design/summary/load/report` + `regime_run --flow`；
  - dialog-control.md bash 改 `*: allow`（headless HTTP 死锁根治；安全靠 edit/write deny + --perm 门禁）。
  - 真实 E2E：dialog-control 设计 mini_wf → 注册 → 运行 → 正确诊断；官方模型下 drive --flow 31.4s COMPLETE 零 ladder。
- **实践暴露问题修复 ✅（2026-08-11）**：supervisor T2 stall 误报根治 + 僵尸进程 bug + 控制对话框容器漂移 +
  A-route 权限死锁 + reporter 噪音 + 易用性（见 TASK 验证记录）。
- **流程热编译/热加载基础设施（WORK_PLAN5 F1–F11）✅**：`src/regime_driver/flow.py`
  `FlowRegistry`（命名 flow 单一真源 + `compile_spec` 统一编译 + 深检门 + 原子替换/旧快照 +
  持久 store `REGIME_FLOW_STORE`，跨 CLI 调用单一真源）+ `regime flow list/validate(--watch)/load/
  reload/rm/inspect`（权限门禁）+ dialog-control A/B 路接入（B 路 `flow list/validate/reload/doctor` 命令、A 路
  plugin `regime_flow_*` 工具）。dialog-control 原 `self.flows` 冗余第二真源已归并删除。
- **L1 预演修复 async drive 双注册任务缺陷 ✅（真实 E2E）**：`drive --async` 子进程现经
  `REGIME_TASK_ID` env + `register(task_id=)` 复用父任务记录（单 id、正确 done/complete，
  消除成功误报 crashed/任务孤儿/重复记录）。**覆盖率基线 C1 ✅**（pytest-cov，floor 68 防矩阵抖动）；
  **dialog-control doctor 自检 C2 ✅**；**主机模式 agent 模板 C4 ✅**（`docs/howto/host-mode-agents.md`）。
- **真实 CI 已转绿（WORK_PLAN6 II ✅）**：GitHub Actions 上 `unit · py3.11/py3.12` + `real-worker E2E`
  全 success（修复 `secrets` 不可用于 job 级 if + worker `ensure()` 死 api_key 测试隔离缺陷）。
  见 `https://github.com/haberzero/regime-driver/actions`。
- **发布就绪（WORK_PLAN6 III/IV/V 大部分 ✅）**：控制对话框插件去硬编码（`REGIME_BIN`）、文档一致性、
  `README.en.md` 英文版、`SECURITY.md`/`CONTRIBUTING.md`、KNOWN_LIMITS 对外摘要、MIT License。
- **项目已公开上传 GitHub public**：https://github.com/haberzero/regime-driver （`main`，SSH 认证，已获用户明确授权 push）。
- 测试基线 356 passed。
- **模型**：默认 `deepseek-api/deepseek-v4-flash`（DeepSeek 官方 API），主机+worker/dialog-control 全统一；
  key 在 `~/.regime/keys/opencode-go.key`（gitignore）或 auth.json；自检 `regime doctor`。
- **容器**：`opencode-worker`（4097，默认执行器，`--pure` 无插件）、`opencode-dialog-control`（4098，A 路验证窗，
  host 网络，带 regime-dialog-control 插件）、以及**每工作区一个的 `opencode-worker-<ws>` 实例**（`regime worker`
  管理，物理隔离）。`opencode-autopilot` / `opencode-setup`（M0/web 旧窗）**已退役删除（2026-08-12）**。
- **架构**：对等多状态机网络（看门狗根不变量）+ 进程外 `supervisor`（收编 M0，含智能元分析）+
  `task` 注册表 + `Reporter` 报告总线 + 控制对话框双路 + **`drive` 一键自驱动栈** +
  **`WorkerPool` 多实例工作区隔离**（每工作区一个 opencode 实例，角色用 session）+
  **`Parallel` 并发隔离并行任务** + **`chaos` 故障注入/恢复演练**。
- **一键起栈**：`ops/up.sh`（worker/dialog-control 一键构建+拉起+等健康，sg fallback，--rebuild，注入 opencode-go key）。
- **技术债**：G1–G14 全清（`TECH_DEBT.md`），无已知双通道/半接通死能力/双写真相。
- **测试架构**：`tests/test_e2e_worker.py`（REGIME_E2E 门控，含真实 drive/supervisor 无假停滞 +
  T1→L4 重启恢复 + 元分析真实模型）+ 死代码守卫 `test_deadcode.py`（扩 drive/dialog_control/worker/parallel/chaos）+
  CLI 命令级测试 `test_cli.py`。

### 下一 session 主线任务（唯一指针，2026-08-13）

> **下一 session 主攻「内部代码质量检查 + 工作日志流程深度核查」**（用户指示：代码质量分析
> 不能只靠 pytest——pytest 全绿 ≠ 质量好。需对 regime 自身的工作成果与运行日志做深度核查，
> 抓出藏得更深的问题）。数据已归档入库（见下方数据地图），`ops/quality_run.py` 可复用重跑。

#### 数据地图（已归档入库，防 /tmp 丢失）

| 数据 | 位置 | 内容 |
|---|---|---|
| **质量套件产物** | `tasks_docs/quality_run_archive/artifacts/<12任务>/` | 每任务模块代码 + 测试（宿主 pytest 通过，**但需深审**） |
| 质量报告 | `tasks_docs/quality_run_archive/quality-report.json` | 43 次运行（outcome / host_pytest / reviewer verdicts） |
| **事件账本** | `tasks_docs/quality_run_archive/events.jsonl`（133KB） | node_enter/node_done/transition/reviewer_verdict/dispatch_error/outcome 全事件链 |
| 报告日志 | `tasks_docs/quality_run_archive/journal.jsonl`（6.2MB） | WorkflowUnit 全链路报告（每节点指令/汇报/判定） |
| 任务明细 | `tasks_docs/quality_run_archive/tasks/*.out + *.summary.json` | 每任务 drive 输出与最终结果 |
| 第一次耐久 | `tasks_docs/durability_run_archive/` | 2h 简单任务耐久（38 任务）原始数据 + 报告 |
| 被中断的耐久 | `tasks_docs/durability_run_archive/run2/` | 限并发方案被质量验证取代，仅少量样本 |

#### 核查任务清单（不依赖 pytest）

**A. 产物代码深度审查（每任务独立只读 review，12 个）**
1. **测试质量**：断言是否真实（真断言 vs 软断言/空断言）、是否覆盖规格要求的全部边界、有无"测了个寂寞"（测试绿但逻辑未验）。
2. **代码质量**：正确性边界（并发/异常/空输入）、结构/命名/死代码、安全（注入/临时文件/路径处理）、健壮性（重试/资源释放）。
3. **规格符合度**：规格要求的每个 API/行为是否实现、参数语义是否一致。
4. 产出：每任务发现清单（blocker/warning/nit），与宿主 pytest 对照——找出"测试绿但代码有问题"的样本。

**B. reviewer 判定质量核查（从 events.jsonl 提取全部 reviewer_verdict）**
1. verdict/reason 是否实质（1-2 句真理由 vs 套话）。
2. confidence 分布（有无低置信度却 advance）。
3. 是否"过场判定"（对明显缺陷也放行）——对照 A 的发现。
4. gate 拒绝事件（task_sched design gate exhausted）的具体原因链。
5. 结论：审查门到底拦截了什么、漏了什么。

**C. 工作日志流程核查（journal + 事件链）**
1. 每任务节点推进完整性（understand→…→wrap 是否走全，有无跳步）。
2. **developer 是否在 understand/read_code 节点就提前写代码**（已观察到模型跳过设计直接实现）——流程纪律问题，是否需更强节点约束。
3. transition 决策（reuse/rotate）是否符合预期、有无异常流转。
4. 全量异常事件收集：dispatch_error / 重试 / 超时 / 停滞。
5. 4 个非 complete 的完整事件链复盘（见 D）。

**D. 待深挖线索（本次发现未深究，优先级最高）**
1. **lru_ttl 首轮：developer 连续 7 次输出截断草稿 → 监督升 human**。根因假设：模型输出截断 / worker 会话退化 / 上下文溢出。查该任务完整事件链 + 会话消息。
2. **task_sched design gate exhausted**：reviewer 为何反复输出不合法 verdict。查 reviewer_verdict 事件 + gate 拒绝原因。
3. **json_config blocked（18.5s 极快）**：reviewer 为何判 blocked。查事件链。
4. **worker `MaxListenersExceeded` 警告**（`docker logs opencode-worker` 可见）：会话累积导致 opencode 进程内部监听器泄漏——潜在长期退化根因。
5. **4 个非 complete 全在首轮、后续自愈**：是真自愈还是偶然。对比首轮与后续轮次事件差异。
6. **developer 提前实现**：模型跳流程 vs 需要更强节点指令约束。

**E. 处置**：发现系统问题 → 修复 → 全量测试零回归 → commit（走 code-workflow + general 只读 review）。

#### 环境状态（交接时）

- `opencode-worker` / `opencode-dialog-control` 容器健康；worker 有会话累积残留（`regime sessions --clean` 可清）。
- 测试基线 **407 passed**；`sync_templates.py --check` 绿。
- 上一批修复：**reviewer agent `bash` 改 `"*": deny`**（headless 死锁，见 `quality_report.md` §2/§5）。
- 复用工具：`ops/quality_tasks.py`（套件）、`ops/quality_run.py --tasks <id>`（单任务重跑）。
- 历史主线（已完成）：WORK_PLAN7 供给就绪 + WORK_PLAN6 耐久 + L2 资源治理 + 版本护栏 + 示例流程 + 文档站重构 + 术语改名 + 质量收益验证。
- 剩余候选：**V-2 PyPI（待用户）**、夜间稳态耐久二次验证（简单任务限并发基线，可选）。

### 已完成主线（历史，参考）

- **P0#1/P0#2/P1#3/P1#4/P2#5** ✅：见上方表格。
- **worker 工作区隔离 / 并行任务 / 混沌 / 并行任务控制面 / 模型统一 / 易用性** ✅：见上方表格 + `docs/subsystems/*`。
- **T1/T2 A 路验证** ✅：经专用 控制对话框容器 + HTTP 驱动打通；修 regime-dialog-control.js 三个真 bug。
- **T3/T4/T5/T7/T6** ✅：非阻塞作业、插件 job 工具、权限策略、文档同步、FakeClient 评估定案。
- **WORK_PLAN4** ✅：I1/I2 保障、E1 SSE 摄入+重连、R-A/R-B/R-C（Reporter 报告总线 + `regime report` 看板 + 模板 + 保留策略）。
- **技术债治理** ✅：G1–G14 全清（含 G6 M0 系统化收编、死代码守卫、静默兜底修复、权限强制、文档单点真理）。
- **测试架构** ✅：T-A E2E 系统化、T-B 控制对话框容器、T-C A 路打通、T-E 交接收口。

**历史里程碑**：M0–M4 ✅、架构 v2/v3/v4 ✅、对等多状态机重构 ✅、E2E 卡顿修复 ✅、mock ✅、WORK_PLAN1/2/3 ✅。

**待决技术项**：monkey 用 `RolePolicy(transition_mode=ROTATE)` 构造时 dataclass 字段默认值遮蔽类属性（测试已规避）。历时超时模型：`default_deadline_sec` + `global_deadline_sec`。

阅读顺序：`docs/README.md`（导航，先看）→ `docs/CLI_REFERENCE.md`（命令/配置参考）→ `docs/guide/`（教程）→ `docs/ARCHITECTURE.md`（架构，`architecture/02_statechart_network.md` 最终架构）→ `docs/SUBSYSTEM_DESIGN.md`（子系统，`subsystems/*`）→ `docs/KNOWN_LIMITS.md`（边界）→ `docs/howto/`（实操）。书写准则：`docs/WRITING_GUIDE.md`；文档治理：`workflow-regime/skills/doc-governance/SKILL.md`。

**关键决策速记**：审查者常驻 session（只读不可跑命令，可要求开发者跑）；开发者 1 个 session（基础 AGENTS.md，不自查，段末 `[WORK_DONE]` 汇报，5 轮里程碑询问）；**角色是独立个体，靠交接单协作，审查者只读汇报单不读开发者记忆**；**session 自评驱动脑容量交接（40% 自评/70% 紧急），非机器人硬掐断**；**审查者流转时开发者 session 禁止切换（稳定锚点）**；交接文档 session 直接写工作区，载体文件系统 + Ledger 审计；策略可编程（Python+模板，参考策略预置）；JSON 契约与镜像自主决定；全局状态清单（开发者不可见）单独设计；**安全监控独立线程 + 确定性 abort 紧急停止**；**对等多状态机网络（看门狗=无智能状态机+根不变量运行时强制）**；**控制对话框双路：opencode 作载体（A 路）+ DialogControlUnit 程序化面（B 路），共用 CLI 契约**。

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

# 流程热编译/热加载（WORK_PLAN5; 命名 flow 单一真源, 跨进程持久于 REGIME_FLOW_STORE, 默认 ~/.regime/flows）
conda run -n regime-driver regime flow list [--json]                       # 列出已注册 flow
conda run -n regime-driver regime flow validate <regime.json> [--watch] [--json]  # 热校验(可 --watch 编辑即校验)
conda run -n regime-driver regime flow load <regime.json> [--name <n>] [--json]   # 加载+深检+注册 (写)
conda run -n regime-driver regime flow reload <name> [--json]              # 原子热重载, 运行中workflow保持旧快照 (写)
conda run -n regime-driver regime flow rm <name> [--json]                  # 移除 (写)
conda run -n regime-driver regime flow inspect <name> [--json]

# 报告总线（宏观看板 / 因果链 / 模板 / 保留）
conda run -n regime-driver regime report --journal /tmp/rep.jsonl [--wf id] [--tasks-dir] [--json]
conda run -n regime-driver regime report <object> --trace --journal /tmp/rep.jsonl
conda run -n regime-driver regime report --journal /tmp/rep.jsonl --template milestone|blocker|period|activity
conda run -n regime-driver regime report --journal /tmp/rep.jsonl --prune --max-records 500

# 会话 / 事件 / 控制对话框
conda run -n regime-driver regime sessions|session <id> send|reply|events --ledger ... --json
conda run -n regime-driver regime dialog --live --base http://127.0.0.1:4097 --perm run

# 任务注册表（收编 oc-task）
conda run -n regime-driver regime task list|status|logs|stop|clean <task-id> [--json]

# 进程外监督（收编 supervisor；宿主独立时钟 + docker 控制）
conda run -n regime-driver regime supervisor --base http://127.0.0.1:4097 --session <id> --container opencode-worker --reporter /tmp/sup.jsonl [--meta] [--once]

# 一键起栈（P1#3: worker/控制对话框容器构建+拉起+等健康）
ops/up.sh all          # worker+dialog-control
ops/up.sh dialog-control --rebuild   # 强制重建固化镜像再起

# 多 opencode 实例工作区隔离（P2: 每工作区一个实例, 无重复, 角色用session）
export REGIME_WORKSPACE_ROOT=~/oc-meta/workspaces   # 工作区根(默认)
export REGIME_WORKER_MAX_INSTANCES=8                # 可选: 并行任务实例上限
conda run -n regime-driver regime worker up <ws>     # 起/复用工作区实例(不重复)
conda run -n regime-driver regime worker list        # 列实例+健康
conda run -n regime-driver regime worker base <ws>   # 工作区实例 base_url
conda run -n regime-driver regime worker down <ws>   # 停止并移除实例(含chown回宿主)
conda run -n regime-driver regime worker prune [--dry-run] [--max-instances N]  # 回收空闲实例/设上限
conda run -n regime-driver regime drive "<任务>" --workspace <ws> --container opencode-worker-<ws> --reporter /tmp/rep.jsonl   # 在隔离工作区跑整套栈

# 并发隔离并行任务（P2: N个任务各自工作区并行全栈）
conda run -n regime-driver regime drive-many "t1" "t2" "t3" \
  --workspaces "wsA,wsB,wsC" --workers 2 --deadline 600 --reporter /tmp/parallel.jsonl

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

# 控制对话框 A 路验证窗（opencode-dialog-control 容器, host 网络, 4098）— 见 docs/howto/dialog-control-window.md
sg docker -c 'docker build -f docker/Dockerfile.dialog-control -t opencode-dialog-control:1.18.11 .'
sg docker -c 'docker rm -f opencode-dialog-control; docker run -d --name opencode-dialog-control --network host -e DEEPSEEK_API_KEY="$(cat /tmp/dk.txt)" -e OPENCODE_PORT=4098 opencode-dialog-control:1.18.11'
curl -s http://127.0.0.1:4098/global/health

# （旧 M0 监督器命令已删除；现行用 `regime drive`/`regime supervisor`）
```
