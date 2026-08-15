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

> **当前主线（唯一指针，2026-08-15）**：技术文档全方位同步 + 版本号统一 v0.1 已完成
> （commit `9dd10d3` + `db99aaa` + `1bed87f` + `d9d9b97`，658 passed 零回归 + general review
> **APPROVE 0 blocker** + 审计二轮清尾）。
> **下一 session 主攻：V-2 PyPI 发布**（用户 token 就绪即可 `python -m build && twine upload dist/*`；
> `dist/regime_driver-0.1.0-py3-none-any.whl` 已重建并通过隔离安装验证），随后按优先级表推进。

### 当前状态速览（2026-08-15）

> **技术文档全方位同步 + 版本号统一 v0.1（2026-08-15，commit 9dd10d3 + db99aaa + 1bed87f，
> 658 passed 零回归）**：①**版本统一 v0.1**——`__version__` 0.3.0→0.1.0（唯一真源，pyproject 动态读），
> README 中英 / docs index / 描述符 schema 版本（regime.json/example/flow_v13/flow_spec）全部对齐，
> wheel 重建 0.1.0；②**代码注释清理**（workflow 5 批次 28 文件）——任务代号残留移除 + 4 断链文档指针
> 修正 + 历史叙述改现在时；③**三并行审计修复**（用户文档/架构子系统/代码注释）——P0 事实错误
> （README e2e 路径、README.en docker-in-wheel 声明、max_reviewer_retries 2→3、verify_enabled
> true→false、config.example.toml 断链）、P1 CLI 缺参补齐（run/preflight/status/report/dialog）、
> P2 红线清理（18 文档）、P3 一致性（permission `_COMMAND_LEVEL` 补 drive-many/chaos/web + 测试、
> 02_configuration env 表、04_permissions 命令表）；④stale-wrong 修复（ESCALATE 幽灵动作、
> capabilities 6→7 子面、03_boundary 角色注册已实现、08_mock DriveClient 协议）。收尾 commit
> `d9d9b97`：general review **APPROVE 0 blocker** + 审计二轮清尾（data/ 与真源模板任务代号清零、
> 断链指针、历史叙述去功能化、review N1 版本戳、opencode.py 协议声明），wheel 0.1.0 重建+隔离验证。
> **下一步 = V-2 PyPI 发布**。详见 `tasks_docs/MAIN_TASKS.md` 当前主线。

> **发布就绪第二阶段（2026-08-15，commit aa9bf31 + 78f5c26，656 passed 零回归）**：
> ①**全局模式标注不推荐**——scaffold/setup 输出缺点说明（opencode 无按 agent 隔离工具机制，源码核验
> Agent.Info 无 tools 字段、permission 只认全量 `*` deny、插件工具全局注册），JSON 输出
> `global_not_recommended: true`；②**工作区预检** `precheck_workspace()`——`.opencode/` 已有用户文件
> （不覆盖）、路径冲突（建议先整理工作区）、git `.gitignore` 建议、opencode 运行中（装完需重启），
> 取部署前状态（不被 manifest 掩盖），`pgrep -x opencode` 精确匹配；③**真实分发验证 ✅**——真实
> opencode 1.18.15 隔离工作区实测：`.opencode/` 被自动发现（`/config` 含 file:// 插件）、dialog-control/
> reviewer agent 出现、tools ids 含全部 regime_* 工具、内置 agents 共存、卸载零残留（沙箱内 ServeError
> 为隔离 XDG+npm 伪环境限制，真实容器环境验证通过）；④文档同步（05_setup/04_blueprint/README/01_cli/
> capabilities/agent-handbook）。**下一步 = general review 收口 → V-2 PyPI 发布**。详见
> `tasks_docs/MAIN_TASKS.md` 当前主线。

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
- **初学者读者视角文档批评 + 落地（✅ 2026-08-12）**：以普通读者视角通读全部对外文档产出批评报告，
  逐条核实代码后全面改进——guide 编号去重（03 双号→00-07）、
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
  `e2e-real` job；`e2e_tests/test_e2e_worker.py` 保留本地/手动可用（`REGIME_E2E=1`）。
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
  A-route 权限死锁 + reporter 噪音 + 易用性（见 `tasks_docs/WORKLOG.md` 验证记录）。
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
- **测试架构**：`e2e_tests/test_e2e_worker.py`（REGIME_E2E 门控，含真实 drive/supervisor 无假停滞 +
  T1→L4 重启恢复 + 元分析真实模型）+ 死代码守卫 `test_deadcode.py`（扩 drive/dialog_control/worker/parallel/chaos）+
  CLI 命令级测试 `test_cli.py`。

### 下一 session 主线任务（唯一指针，2026-08-14 深夜）

> **本 session 已完成：文档体系 + 自说明体系全方位同步**（主线交付，用户指示：技术文档必须更新到
> 最新状态避免误导；试用 regime-driver 的智能体必须获得完善且合理的说明书；相关插件可能需更新）。
> 交接前 grep 实测审计的缺口已全部补齐并复核。
>
> **已完成交付**（详情见 `tasks_docs/WORKLOG.md` 最新 DONE 条目 + `MAIN_TASKS.md`）：
> ① **读者层**：`docs/guide/*` 8 篇 + `docs/howto/*` 7 篇 + `README`/`README.en` 补全五阶段新特性
> （制度一等公民 / 整制度设计 / 意图级 design / hooks.py 扩展点 / ask_human+decide / verify 白名单）；
> ② **参考/架构/子系统复核**：01_cli `regime regime` 组完整性确认；architecture/01 补阶段0监督统一修正；
> subsystems/01_drive 修正监督归属、06 意图级表述、07 补 regime 契约；
> ③ **自说明体系**：插件补 `regime_regime_inspect/reload/rm` + `regime_run --regime-name` 转发（19→22 工具）；
> ④ **智能体说明书**（用户明确要求）：`.opencode/agent-handbook.md` 随 wheel 分发；
> ⑤ **验证门**：610 passed 零回归 + 守卫/sync_templates/check_capabilities 全绿 + general review 两轮 0 blocker；
> ⑥ **mkdocs 本地挂起**：当前不复现（本地 2-3s 可构建），验证路径可用。
> **测试基线 610 passed 零回归**；sync_templates / check_capabilities / 守卫全绿。

> **本 session 后续：夜间长跑 + verify 白名单配置漂移真实 bug 根治**（2026-08-15 凌晨）：
> 全 5 任务长跑（`tasks_docs/nightly_run_archive/20260814-222131/`）——4 complete + distributed_scheduler
> blocked@test（watchdog kill）。**根因**：FlowRegistry 持久 store 残留旧 `sg docker -c` 包装 verify 命令
> → 运行时白名单拒绝（rc=None）→ judge 无 pytest 证据 → 质询重跑 + dispatch 瞬时超时 → watchdog kill。
> **修复**：`core/verify_spec.py`（白名单上移 core，单点真理）+ `core/validate.py` deep_validate 白名单预检
> + `FlowRegistry._load_store` 装载期 verify 形状校验（W1 闭环，review 抓出）+ store reload。
> **测试基线 612 passed 零回归**；报告 `tasks_docs/quality_report.md` §8。
> **重跑验证（✅）**：distributed_scheduler 单任务重跑 complete（1504.9s）+ 宿主 pytest 26p/0f +
> verify rc=0（test 门拿到真实证据）——bug 修复闭环实证成功。归档
> `tasks_docs/nightly_run_archive/recheck-verify-20260815-002235/`。

> **本 session 后续（2026-08-15 下午）：主控对话框使用模式变革**（元层评估定案——本 session 实际承担了
> 主控对话框职责，直接 bash 直连 CLI 比包装工具高效；原始设计意图=对话框永不因工具使用被阻塞）：
> ① dialog-control.md 重写为**自由 bash 直连 regime CLI** + agent-handbook 必读 + 诊断流程章节；
> ② agent-handbook 新增 §5 非阻塞后台运行与事后查看（--async + job status/logs + web 观察窗）；
> ③ **新增 `regime web`** 只读观察窗（`app/observe.py`，stdlib，HTML 面板 + JSON API，纯消费者零写操作）；
> ④ **新增 `regime job logs <id>`**（--async 捕获输出事后查看）；⑤ 插件降级为可选引导（非主路径）；
> ⑥ 文档同步（01_cli/capabilities 18 顶层/guide/howto）。**测试基线 624 passed 零回归**；general review
> 两轮 0 blocker（XSS 修复 + best-effort 违约 + 编号等 11 项全收口）。

> **本 session 后续（第二轮夜间长跑 + 两个新真实 bug 根治，2026-08-15 清晨）**：
> verify 彻底修复后全套件重跑——4 complete + payment_ledger(error@design 真实失败)；**verify 根除实证成功**
> （distributed_scheduler 三次 verify rc=0）。深挖 payment_ledger 失败暴露两个新 bug：
> ①**extract_json 鲁棒性**（散文未闭合引号/字面花括号污染单次扫描）→ 每个 `{` 候选独立跟踪字符串状态；
> ②**judge 在流式 partial 上判定**（review 实证真实根因：`_latest_assistant` 不检查 completed，对比 agent
> 路径）→ judge 等待 `completed` + 跳过 abort draft。payment_ledger 重跑 complete（30p/0f）闭环实证。
> 归档 `tasks_docs/nightly_run_archive/nightly2-20260815-020027/` + `recheck-pl-20260815-040327/`；
> 报告 `tasks_docs/quality_report.md` §8.6。**测试基线 618 passed 零回归**。

> **上一 session 已完成：体系化重构 全部五阶段（0/1/2/3/4）**（用户授权破坏性重构，蓝图
> `tasks_docs/_regime_redesign.md` 已总结入 WORKLOG 并删除）。宏观根因（3 个体系化根因：
> Regime 非一等公民 / 监督职责分裂 / 核心语义未在底层定义）已全部落地解决。
>
> **阶段 0（`989dac6`，监督统一抽象，W1/W2 根治）**：drive 模式会话级监督归 in-process watchdog；
> 进程外退为 T1/deadline/meta；watchdog_fire 落 journal；SseActivity 单一活性源。
>
> **阶段 1（`bb73524`/`4e1f2f7`/`ea50be8`，Regime 一等公民）**：`regime.py` + RegimeRegistry +
> `from_regime` + `regime regime` CLI + `run/drive --regime-name`；1c 独立 supervisor 判定统一到
> watchdog_policy 规则引擎（删 SessionWatch/_verdict_for_stall，meta 只升不降）；1d run-many/
> drive-many `--regime-name` + 对话框整制度设计入口。
>
> **阶段 2（`d1fe9f4`，统一扩展点模型）**：`extensions.py` HookRegistry（6 类生命周期 hook +
> rules + tools）+ `~/.regime/hooks.py` 插件；handover 声明式模板化；verify 白名单化消 RCE（W5）；
> 对话框 hook list/path/reload。
>
> **阶段 3（`7a38e9a`，语义契约下放）**：`is_abort_error` 瞬时错误分类（W3，防 ConnectionAbortedError
> 误判）；extract_json 尾部逗号容错（W4）。
>
> **阶段 4（`3b06490`，对话框意图级制度操作面）**：`ask_human` 人工确认点（workflow `_PH_HUMAN` 相 +
> 黑板决策通道 + decide 命令 + 超时兜底）；意图级设计（NL→flow 或整制度 JSON，审查前验证测试→verify）。
>
> 全阶段：每阶段 general 只读 review（0 blocker 收口）+ 全量测试零回归 + 真实 worker 冒烟
> （hooks 6 节点 fire / run-many --regime-name 16s / 语义契约 87.5s / 阶段4 88s 全 complete）。
> **测试基线 610 passed 零回归**；sync_templates / check_capabilities / 守卫全绿。

---

> **下一 session 主线（唯一指针）**：文档体系 + 自说明体系全方位同步**已全部完成**（2026-08-14 夜）。
> 下方"审计结论"（grep 实测）是上一 session 交接时的缺口清单——本次已全部补齐并复核，历史保留供追溯。
> **下一 session 顺延候选**（不变）：**V-2 PyPI**（待用户 token，dist/ 已构建）→ **P-005 测试套件优化** →
> 限并发耐久二次验证 → **GitHub Pages 启用**（Settings→Pages→GitHub Actions）。

### 审计结论（2026-08-14 深夜，grep 实测；本次已全部补齐）

**已同步（各阶段中做过）**：
- `docs/reference/01_cli.md`：`--regime-name` 已列 run/drive/run-many/drive-many 四表；`regime regime`
  list/inspect/design 已列（reload/rm/load 命令表完整性待复核）。
- `docs/reference/02_configuration.md`：human_confirm_timeout_sec/human_default_on_timeout/verify
  白名单/handover 模板 已补；config.example.toml 同步（守卫绿）。
- `docs/reference/03_flow_spec.md`（verify 白名单）、`05_dialog_control_contract.md`（W3/W4/ask_human/
  decide）、`architecture/02_statechart_network.md`（ask_human/verify 白名单）、
  `subsystems/03_parallel.md`（--regime-name）、`04_supervisor.md`（1c 判定统一）、
  `06_dialog_control.md`（design/hook/decide）、`10_extension_points.md`（新）、`capabilities.md`（decide）、
  `KNOWN_LIMITS.md`（verify 阻塞/瞬时错误边界）。
- `.opencode/agent/dialog-control.md`（制度设计/扩展点/ask_human）+ 打包副本（sync_templates 绿）。

**未同步（本次 grep 确认，需更新）**：
- `docs/guide/*`（00-07 共 8 篇）：**零提及**新特性（hooks.py/ask_human/decide/regime-name/整制度
  设计/意图级 design/verify 白名单）。读者层最大缺口。
- `docs/howto/*`（7 篇）：**零提及**新特性。
- `README.md`/`README.en.md`：**零提及**新特性。
- `docs/reference/01_cli.md`：`regime regime` 组 reload/rm/load 是否入册待复核；与 guide 交叉引用待核。
- `docs/architecture/01_principles.md`/`03_boundary.md`/`04_distribution_blueprint.md`、
  `docs/subsystems/01_drive.md`/`02_worker_isolation.md`/`05_chaos.md`/`07_dialog_control_carrier.md`/
  `08_mock.md`/`09_testing_architecture.md`：逐篇复核是否需补新特性表述（多数可不改，但要确认无误导）。
- `.opencode/plugins/regime-dialog-control.js`（19 工具）：已有 regime_regime_design/list +
  regime_run_many --regime-name；**缺** regime_regime_inspect/reload/rm；regime_run 是否转发
  `--regime-name`/`--flow` 待核验；ask_human/decide 是 Dialog> 命令（B 路），插件（A 路壳 CLI）无法
  直连——如需 A 路接入 ask_human 需新增机制，属可选。
- **智能体说明书（用户明确要的交付）**：为"要试用 regime-driver 的智能体"提供完善且合理的说明书——
  把 dialog-control.md + guide + 插件工具说明整合成**一份连贯的 agent 视角手册**（能做什么/命令面/
  插件工具/制度与扩展点/ask_human 交互/踩坑/真实起栈）。

### 任务清单（建议顺序，每项 code-workflow + 质量门 + 全量零回归 + general review）

1. **读者层全面同步（最优先）**：`docs/guide/*` 8 篇 + `docs/howto/*` 7 篇 + `README/README.en`。
   把五阶段新特性补入并"以实跑为准"（指南里的命令真跑一遍验证，不冻结数字）：制度一等公民/
   `--regime-name`/整制度设计/意图级 design/`~/.regime/hooks.py` 扩展点/ask_human+decide/verify
   白名单。注意 guide 是"人类手册"，禁止智能体元信息（AGENTS 硬约束）。
2. **参考/架构/子系统复核**：01_cli（regime regime 组完整性 + 与 guide 交叉引用）；architecture
   01/03/04；subsystems 01/02/05/07/08/09——逐篇核验，消灭误导；单点真理（概念归属不重复）。
3. **自说明体系**：dialog-control.md 完整性复核；插件补 regime_regime_inspect/reload/rm（如适用）
   + 核验 run/drive `--regime-name`/`--flow` 转发；skills/模板核验（漂移守卫已绿）。
4. **智能体说明书**：整合"试用 regime-driver 的智能体说明书"（agent 视角完整手册），随 wheel 分发
   （入 `src/regime_driver/data/` 或文档站，遵守单一真源 + sync_templates）。
5. **验证门**：智能侧说明同步硬约束（settings↔config+02、CLI↔01_cli+插件、信号↔architecture/02+
   subsystems、智能行为↔dialog-control.md、能力↔capabilities）；守卫测试；sync_templates；
   check_capabilities；全量测试零回归；general 只读 review。
6. **mkdocs build 本地挂起（运维项）**：本地 `mkdocs build --strict` 超时挂起（非内容问题，疑似
   主题/CDN 网络；mermaid2 插件只注入 script 标签不下载）。CI docs.yml（GitHub Actions）可构建。
   下一 session 需解决本地验证路径（镜像/缓存/定位挂起根因），否则文档改动无法本地验证。

### 硬约束（交接提醒）

- 智能侧说明同步硬约束（`MAIN_TASKS.md` 顶部）；单点真理；临时文档完成即删（`_` 前缀工作簿总结入
  WORKLOG 即删）；全量测试零回归（`~/miniconda3/envs/regime-driver/bin/python -m pytest tests/`）；
  审查一律 `general` 只读 agent（严禁 reviewer）；push 已授权（见 §3.x，push 前全量测试零回归 +
  review 收口）。
- 任务控制四类文档：MAIN_TASKS / PENDING_TASKS / HANDOVER / WORKLOG；其余临时。

**测试基线**：610 passed 零回归。**环境**：worker/dialog-control 容器健康；conda env 可编辑安装
（Editable → `/home/haber/oc-meta`，含阶段 0-4 全部代码）。

#### 环境核验（2026-08-14 交接时）

| 资源 | 状态 | 说明 |
|---|---|---|
| `opencode-worker` 容器 | ✅ 健康 | opencode 1.18.11，`http://127.0.0.1:4097`，零残留会话 |
| `opencode-dialog-control` 容器 | ✅ 健康 | opencode 1.18.11，端口 4098（A 路验证窗） |
| 宿主 conda env `regime-driver` | ✅ 可编辑安装 | Editable → `/home/haber/oc-meta`，含阶段0-4 全部新代码（regime.py/RegimeRegistry/extensions.py/ask_human 等） |
| 模型 key | ✅ | `DEEPSEEK_API_KEY` / `~/.regime/keys/deepseek.key`，`regime doctor` 全绿 |
| `regime doctor` | ✅ 12 项全过 | worker 健康/版本/key/模板/部署完整性/docker/opencode/conda/session |
| `regime preflight` | ✅ complete | 离线试跑整条 flow 干净完成 |
| sync_templates / check_capabilities | ✅ 绿 | 24 CLI / 3 mounted skills / 11 packaged / 17 covers |
| 守卫测试 | ✅ 过 | test_config_doc_guard + test_cli_doc_guard + test_deadcode + test_package + test_capabilities_map |
| 测试基线 | ✅ 610 passed | 全量零回归（阶段0–4 全部完成后） |

> **注意**：`opencode-dialog-control` 容器内的 regime-driver 是旧 wheel（0.2.0，早于当前统一口径
> 0.1.0，无 `watchdog_policy_json`、`context_handover_policy_json`、`verify`、`regime` 命令）。它仅作
> A 路验证窗，不影响宿主实验（drive/harness 全在宿主源码上跑）。如需同步最新代码用
> `ops/up.sh dialog-control --rebuild`。

#### 遗留问题清单（2026-08-14 深夜，体系化重构阶段 0–4 全部完成后）

**W 类状态更新（全部关闭 ✅）**

| # | 遗留问题 | 状态 | 说明 |
|---|---|---|---|
| W1 | in-process watchdog 未先于外部 supervisor 触发（drive 模式架构债） | ✅ **阶段 0 根治** | drive 模式会话级监督归 in-process watchdog；进程外只留 T1/deadline/meta；fire 落 journal。commit `989dac6` |
| W2 | drive 外部 supervisor T2 只盯 anchor/首个会话 | ✅ **阶段 0 根治** | in-process 经 REPORT 跟随 wait_sid，会话旋转不失焦 |
| W3 | 瞬时性消息 error 被硬编码 BLOCKED（归因过宽） | ✅ **阶段 3 根治** | `is_abort_error` 分类（MessageAbortedError 锚定 vs 瞬时错误继续轮询）；节点 deadline 兜底。commit `7a38e9a` |
| W4 | reviewer 复杂判定仍可能输出散文 | ✅ **阶段 3 缓解** | extract_json 尾部逗号容错 + 已有鲁棒解析/重试；不做散文转判定的语义猜测（保确定性门） |
| W5 | verify 是宿主任意 shell 执行面（RCE 面） | ✅ **阶段 2 根治** | verify 白名单化（`docker exec {container} <白名单程序>`，argv 无宿主 shell，sg 回退再引号化）。commit `d1fe9f4` |
| W6 | 上下文交接 token 读取失败 fail-open | ✅ 已达标 | fail-open 方向正确 + 留痕，无需处理 |
| W-硬编码 | 交接文档模板/提示词/协商流程硬编码 | ✅ **阶段 2 根治** | `document_template`/`opening_template` 声明式化 + handover hook 覆盖 |
| W-自定义 | 自定义/注入回调/确认状态机交互缺失 | ✅ **阶段 2+4 根治** | `~/.regime/hooks.py` 统一扩展点（hooks/rules/tools）+ 对话框 hook 命令 + ask_human 确认点 |
| 1c | 独立 supervisor 判定自研（SessionWatch/_verdict_for_stall） | ✅ **阶段 1c 根治** | 统一到 watchdog_policy 规则引擎（绝对静默时长多级规则）。commit `4e1f2f7` |
| 1d-补 | run-many/drive-many `--regime-name`；对话框制度设计入口 | ✅ **阶段 1d 根治** | StatechartCluster.from_regime + Parallel.regime；dialog design 整制度。commit `ea50be8` |

**P 类（长期搁置，待用户或低优先）**：见 `tasks_docs/PENDING_TASKS.md`（V-2 PyPI 待用户 token、
GitHub Pages 待用户 Settings、P-005 覆盖率、C3 延迟调优、FakeClient 收敛、MaxListeners doctor 检查）。

**产物技术债（任务归档内，已显式登记，非本仓缺陷）**：
- payment_ledger：`_op_keys` 无淘汰策略、内存态无持久化（`20260814-012700/payment_ledger/`）
- kv_cluster：failover 中途崩溃数据丢失窗口（`20260814-012700/kv_cluster/`）
- etl_pipeline：依赖图"建而不用"（执行按插入序）、RateLimitStage `consumed_at` 无界增长
- shop_inventory：`_is_valid_qty` 三处复制、float 计账漂移

**复查工具速查**（WORK_PLAN13 验证复用）：
```bash
# 新超长任务复查（distributed_scheduler, code_workflow_v13 flow, verify+上下文交接）
REGIME_VERIFY_ENABLED=true \
REGIME_CONTEXT_HANDOVER_POLICY_JSON='{"soft_fraction":0.5,"hard_fraction":0.9,"min_continue_nodes":2,"handover_keep_messages":30}' \
conda run -n regime-driver python ops/quality_run.py --root /tmp/recheck-20260814 \
  --archive /tmp/recheck-20260814/archive --tasks distributed_scheduler \
  --clean-sessions --deadline 3600 --stall 300
# 注意：verify 命令在宿主需 `sg docker` 包装（本环境 docker 组权限），已内置于 ops/flow_v13.json
```

#### 数据地图（已归档入库，防 /tmp 丢失）

| 数据 | 位置 | 内容 |
|---|---|---|
| **质量套件产物（旧 12 任务）** | `tasks_docs/quality_run_archive/artifacts/<12任务>/` | 每任务模块代码 + 测试（宿主 pytest 通过，深审结论见 `quality_deep_check.md`） |
| 质量报告（旧 43 次） | `tasks_docs/quality_run_archive/quality-report.json` | 43 次运行（outcome / host_pytest / reviewer verdicts） |
| **WORK_PLAN9 新套件归档** | `tasks_docs/nightly_run_archive/` | 新 4 复杂任务 per-task 全量归档（会话消息快照+完整工作区+journal/events 切片+result.json） |
| **WORK_PLAN13 复查归档** | `tasks_docs/nightly_run_archive/20260814-wp13-recheck/` | distributed_scheduler 超长任务（1127.5s complete，设计门 2 质询 + verify 宿主证据 + wrap 84% 交接）全量归档 |
| 深度核查报告 | `tasks_docs/quality_deep_check.md` | A–E 全项结论 + 两轮改进记录（根因/修复/复核） |
| **主线任务文档** | `tasks_docs/MAIN_TASKS.md` | 当前主线（WORK_PLAN14 候选） + 下一步 + 硬约束 |
| **搁置任务文档** | `tasks_docs/PENDING_TASKS.md` | 阻塞/搁置但有价值的规划 |
| **工作日志文档** | `tasks_docs/WORKLOG.md` | 全部决策/质询/方案取舍/变化前后 |
| 第一次耐久 | `tasks_docs/durability_run_archive/` | 2h 简单任务耐久（38 任务）原始数据 + 报告 |

#### 交接清单（A–E）完成情况

**✅ 全部完成（2026-08-13），结论见 `tasks_docs/quality_deep_check.md`：**

- **A. 产物代码深度审查（12 任务）**：抽查 task_sched/graph_algos/lru_ttl 等——环检测/线程安全/
  边界测试均合格，无"测了个寂寞"。
- **B. reviewer 判定质量核查**：95 条 verdict，低置信度 advance 仅 3 条且均与截断输入相关，
  非"过场判定"；gate 拦截正确。
- **C. 工作日志流程核查**：节点推进完整无跳步；developer 无系统性提前实现。
- **D. 6 条待深挖线索**：全部定性——①lru_ttl 截断→human = event_stream bug 根因（已修复）；
  ②task_sched gate exhausted = 确定性门正确拦截；③json_config blocked = watchdog 重复检测
  （非 reviewer，已更正文档）；④MaxListenersExceeded = opencode 内部问题（非本仓缺陷）；
  ⑤首轮自愈 = 误判偶然性（修复后系统性消除）；⑥跳流程 = 无系统性。
- **E. 处置**：发现 event_stream 真实 bug → 修复 → 415→419 passed 零回归 → commit。

#### 环境状态（交接时）

- `opencode-worker` / `opencode-dialog-control` 容器健康（镜像 `opencode-worker:1.18.11`）。
- 宿主 conda env `regime-driver` **可编辑安装**（Editable → `/home/haber/oc-meta`），
  含 WORK_PLAN10/11/12 全部新代码。测试基线 **469 passed 零回归**；`sync_templates.py --check` 绿；
  `ops/check_capabilities.py` 绿（24 CLI / 3 mounted skills / 11 packaged / 17 covers）。
- **防断裂守卫**：`tests/test_config_doc_guard.py` + `tests/test_cli_doc_guard.py`
  （settings 字段↔config/ref 表一致 + 死字段标 deprecated；CLI 文档无 phantom 参数）。
- **WORK_PLAN10（SSE 活性）**：`app/sse_activity.py` SseActivity 采集器；watchdog/supervisor
  停滞判定以 SSE `/event` 事件流为活性信号（token 计数 step 粒度滞后不可用）。
- **WORK_PLAN11（可编程看门狗）**：`app/watchdog_policy.py` 策略引擎（SessionEvidence/Rule/
  Ladder/WatchdogPolicy）；动作阶梯 nudge→interrupt(PAUSE)→resume→fallback→kill；
  workflow 实现 PAUSE/RESUME/NUDGE/ESCALATE；`settings.watchdog_policy_json` + `auto_resume_sec`。
- **WORK_PLAN12（智能侧说明同步）**：dialog-control.md / 05 契约 / 01_cli / architecture/02 /
  subsystems 全部同步新能力；`[deprecated]` 死配置标清。
- **WORK_PLAN9 套件/归档**：`ops/quality_tasks.py` 4 复杂任务；`ops/quality_run.py` per-task
  全量归档（会话快照+工作区+切片+result.json）+ `--clean-sessions` 归档后执行 + 中断可续；
  `ops/run_nightly.sh` trap EXIT 保证中断也归档。
- **dialog-control 容器版本注意**：容器内 regime-driver 是旧 wheel（0.2.0，早于当前统一口径
  0.1.0，无 `watchdog_policy_json`），仅 A 路验证窗用，**不影响宿主夜间实验**；如需同步最新代码
  用 `ops/up.sh dialog-control --rebuild`。
- 复用工具：`ops/quality_run.py --tasks <id>`（单任务重跑）、`--root <dir>`（产出 quality-report.json
  含 capability_coverage）、`ops/run_nightly.sh`（夜间一键长跑）。
- 历史主线（已完成）：WORK_PLAN7 供给就绪 + WORK_PLAN6 耐久 + L2 资源治理 + 版本护栏 +
  示例流程 + 文档站重构 + 术语改名 + 质量收益验证 + WORK_PLAN8 阶段 1–4 + 分发重构 + 卸载机制 +
  WORK_PLAN9/10/11/12 + **夜间整合重跑（2026-08-14 ✅，见 §8 上方）**。
- 剩余候选：**V-2 PyPI（待用户，dist/ 已构建）**、**P-005 测试套件优化**、
  **限并发耐久二次验证**、**GitHub Pages 启用**（Settings→Pages→GitHub Actions）。

### 本 session 已完成（2026-08-13，8 个 commit）

> 本轮完成了交接清单 A–E（深度核查）+ WORK_PLAN8 阶段 1–4 + 测试套件净化。
> 详细报告：`tasks_docs/quality_deep_check.md`（A–E 结论）、`tasks_docs/MAIN_TASKS.md`（规划）。
| commit | 内容 |
|---|---|
| `5265628` | **深度核查修复真实 bug**：opencode 1.18.11 `/event` SSE 无 `event:` 行，`event_stream` 的 `raw["event"]` 恒 None → T2 活性兜底永久失效（长生成被误判 stalled→abort→截断草稿，lru_ttl 首轮 7 次截断→human 的直接根因）+ journal 被 90% delta 噪音淹没。修复 `data.type` 回退。 |
| `c442006` | **复核+改进**：T2 活性链可观测性（sse_error/sse_type_unresolved 审计 + _safe_record）、abort 截断消息不推进（error/finish=None）、report_len_warn 审计、preflight 诚实提示（_note）、json_config 文档失实更正。F 更正（低置信度 advance 非缺陷）。 |
| `172f01d` | **WORK_PLAN8 阶段1**：试用体系重构为能力覆盖引擎——8 精选任务（4 深度保留 + refactor_legacy/fix_bugs/multi_module/design_decision 新形态），harness 支持 seed_files 预置/多文件收集/能力覆盖报告。 |
| `d6181d5` | **WORK_PLAN8 阶段2**：skill 注入对称化——修复 agent 节点 skill 死配置（`_build_instruction` 不加载 skill），新建 developer-quality skill 挂 implement/wrap，config/scaffold 同步。 |
| `d2ff8db` | **WORK_PLAN8 阶段3**：对话框成为全能力引导枢纽——`capabilities` 命令（按场景分组能力地图）+ GUIDE 值守模式章节。 |
| `68b3d91` | **WORK_PLAN8 阶段4**：capabilities.md 能力地图单点真理 + `ops/check_capabilities.py` 交叉核对脚本 + mkdocs 入参考区。 |
| `3377500` | **测试套件净化**：E2E 真实调用移出 `tests/`→`e2e_tests/`（不再被收集），warnings 清零（专用 basetemp），提速 60%（114s→46s），419 passed。 |
| `d1216c2` | **部署审计**：硬编码清零（worker 默认路径 `oc-meta`→`~/.regime/workspaces`）、doctor 环境检测（docker/opencode/conda/平台）+ 部署路径引导、scaffold 部署 opencode.json/config.example（真源随 wheel）。 |
| `3b5aa23` | **分发重构**：插件 + dialog-control agent + package.json 随 wheel 分发（经 opencode 官方本地插件机制），scaffold 一键装配主机 opencode 主载体；插件 BASE 支持 `REGIME_WORKER_BASE`（远程/docker worker）。 |
| `f1fe51a` | **分发合规**：docker 构建资产移出 wheel（GitHub 提供），插件去容器路径回退（纯 PATH 解析）；wheel 合规审计（无 docker/主机路径）+ 反向断言守卫。 |
| `32da91a` | **分发蓝图 + setup**：`docs/architecture/04_distribution_blueprint.md`（渠道/内容归属/数据位置/用户路径全情形）；`regime setup` 引导安装（检测+装配+分步指引）。 |
| `9ec570d` | **容器重建**：dialog-control 镜像加 regime env 入 PATH（修 A 路插件 regime 解析）。 |
| `4918e5f` | **卸载与恢复**：部署清单 manifest（`.regime-deployed.json` 含 sha256）+ `regime uninstall` 安全移除（保留用户改动）+ doctor 部署完整性检测。 |
| `4967579` | **文档体系同步**：插件随 wheel + 主控需插件新表述、god 残留清理、setup/uninstall 登记、单一真源表更新。 |
| `af4058f` | **chore**：gitignore dist/build；push 到 GitHub。 |
| `9aa4f3f` | **交接+文档清洁**：HANDOVER 更新 + 删除 10 个已完成历史规划/一次性审查（-1197 行）+ 引用修正 + README 状态更新。 |
| `d7dd9c4` | **任务控制体系重构**：四类关键文档（MAIN_TASKS/PENDING_TASKS/WORKLOG/HANDOVER）+ 临时文档纪律 + AGENTS.md 重写记录体系 + task-control 规范收敛（去 04 决策记录，02→main_tasks）。 |

**关键成果**：所有交接发现（D1–D6 + A–F）已全部修复并经测试/真实运行核实；WORK_PLAN8
建设性重构阶段 1–4 完成并各自真实验证；唯一未执行 = 阶段 5 夜间整合重跑（属验证非修复）。

### 本 session 已完成（2026-08-13 夜，WORK_PLAN9，2 个 commit）

> 本轮完成 WORK_PLAN9 体系重构：watchdog 误杀修复 + 复杂任务套件 + per-task
> 全量归档/清理重建。冒烟验证：payment_ledger 复杂任务 complete + 宿主 pytest
> 34p/0f + 2 verdicts + 全量归档含会话消息快照。

| commit | 内容 |
|---|---|
| `24f01d1` | **watchdog thinking 误杀修复**：reasoning 令牌计入活性（`_report_to_watchdog` 传 reasoning + `_detect`/`SessionWatch` 双维度判定）+ STOP/超时 abort 会话防孤儿。测试 +9。 |
| `757bd3c` | **WORK_PLAN9 套件/留档/清理**：4 复杂任务套件 + per-task 隔离/全量归档/归档后清理/中断可续 + capabilities §五 声明检查 + 冒烟归档入库。 |

**关键成果**：框架误杀根因（thinking 盲区：watchdog 只统计文本令牌）三处修复；
任务套件从 8 浅任务变为 4 复杂工程任务；日志留档改为 per-task 全量归档（会话
消息快照可回溯 reasoning 推理过程）；清理机制改为归档后才清理 + 中断可续。
全量 438 passed 零回归，general 只读 review 0 blocker。

> **注**：本轮的 `24f01d1`（reasoning 令牌计入活性）是**过渡方案**，后续被 WORK_PLAN10
> （SSE 事件流活性）取代——源码实证 session_tokens 单步长思考期间恒 0，token 计数
> 不能作流式活性信号。**当前架构活性信号 = SSE 事件流，非 reasoning/token。**

### 本 session 已完成（2026-08-13 深夜，WORK_PLAN10，T2 停滞判定 SSE 活性化）

> 用户授权深度破坏性重构。基于 opencode v1.18.11 源码级实证（processor.ts
> step-finish 才记账 token + 异步 projector 写库 → session_tokens 单步长思考恒 0），
> 判定 token 计数不能作为流式活性信号，SSE `/event` 事件流是唯一即时活性信号。

| commit | 内容 |
|---|---|
| （本 commit） | **T2 停滞判定 SSE 活性化**：新增 `app/sse_activity.py`（`SseActivity` daemon 线程订阅 `/event` 维护 {sid: last_activity_ts}）；`watchdog_unit._detect` 改用 activity_ts 判停滞（含 `_first_busy` 首次 busy 锚定）；`workflow_unit` 采集 SSE 活性随 REPORT 喂给 watchdog；`supervisor.SessionWatch` 简化为纯 SSE 活性；`mock_client` 新增 event_stream 模拟 + delay 期间 busy+streaming。测试 +9（SseActivity 8 + preflight 慢生成）。 |

**关键成果**：从"token 计数判活性"（根本错误信号）转为"SSE 事件流判活性"
（opencode 唯一即时信号），修复长思考误杀。真实验证：payment_ledger complete
462s（上次 144s 被误杀）、regime run complete 170s、长思考 30s 全程活性、
真卡死仍判 stall。全量 438 passed 零回归，general 只读 review 0 blocker。

### 本 session 已完成（2026-08-13 深夜，WORK_PLAN11，可编程看门狗策略引擎）

> 用户构想：看门狗不硬性杀死，引入多级判定（先中断→等待→恢复，只有最终兜底才杀死）；
> 允许用户注入检测机制；支持智能判断是否真死机。

| commit | 内容 |
|---|---|
| `3f48c42` | **WORK_PLAN11 策略引擎**：`watchdog_policy.py`（SessionEvidence/Rule/Ladder/WatchdogPolicy/policy_from_json）；`watchdog_unit` 改策略驱动 + paused 不重复中断 + 自动 RESUME；`workflow_unit` 实现 PAUSE/RESUME/NUDGE/ESCALATE + paused 持续上报；settings 加 watchdog_policy_json/auto_resume_sec。 |
| `33a8462` | **WORK_PLAN11 配套**：policy 25 项测试（ladder/decide/meta-gated/自动RESUME/中断恢复）+ 文档。 |

**关键成果**：watchdog 从硬编码阈值 → 四级策略引擎（信号/规则/阶梯/配置）。PAUSE 中断
当前生成+保持会话+冻结推进，RESUME 注入"继续"续接，只有 kill 是最终兜底。真实验证：
payment_ledger complete 265s 零误杀、regime run complete 88s。全量 463 passed 零回归。

### 本 session 已完成（2026-08-14 凌晨，WORK_PLAN12，智能侧说明同步 + 防断裂工作流）

> 用户指出：提供给状态机/对话框的说明过期，导致智能照旧文档调用不存在的 CLI 参数、
> 误把"自动中断续跑"当失败。审计后发现 WORK_PLAN10/11 未同步智能操作层。

| commit | 内容 |
|---|---|
| `828f80c` | **WORK_PLAN12 说明同步**：01_cli 修 run-many/run/drive/supervisor 参数表 + 中断恢复小节；05 契约 §4.1 中断恢复诊断；02_configuration + config 补 watchdog_policy_json/auto_resume_sec + 标死配置 [deprecated]；dialog-control.md 运行时中断恢复段；architecture/02 策略引擎+全信号时序；subsystems 去 Settings.policy 残留；guide/capabilities 同步。 |
| `815a1f0` | **WORK_PLAN12 防断裂守卫**：test_config_doc_guard + test_cli_doc_guard + MAIN_TASKS 智能侧说明同步硬约束 checklist。 |

**关键成果**：智能侧说明与功能一致，杜绝"说明过期"复发。新增 6 项守卫测试
（settings 字段↔config/ref 一致 + 死字段 deprecated + CLI 文档无 phantom 参数）。
全量 469 passed 零回归，真实 worker 冒烟 complete 94.6s。

### 本 session 已完成（2026-08-14，夜间整合重跑 + WORK_PLAN13）

> 用户确认后直接全量开跑。本轮完成了 WORK_PLAN8 阶段5 + WORK_PLAN9 验证的最后一环
> ——在最新架构（SSE 活性 watchdog + 可编程策略引擎 + 智能侧说明）下全链路重跑，
> 并随后实施了 WORK_PLAN13 深度迭代（用户授权破坏性重构 + 激进推进）。

**结果**：4/4 复杂任务 complete（shop_inventory 349s / kv_cluster 664s / payment_ledger 499s /
etl_pipeline 515s）；宿主独立 pytest 全 0 failed（63/22/27/28 passed，140 断言累计）；
reviewer verdicts 2/2/3/2（实质判定）；**能力覆盖 17/17**（0 uncovered）；零 ladder、零误杀。
全量测试 469 passed 零回归；sync_templates/check_capabilities 守卫绿。

**产出**：`tasks_docs/nightly_run_archive/20260814-012700/`（per-task 会话快照 + 完整工作区 +
journal/events 切片 + result.json + quality-report.json + run.log）；`tasks_docs/quality_report.md` §7
报告；MAIN_TASKS/WORKLOG/HANDOVER 已同步。

**工程结论**：WORK_PLAN10（SSE 活性）与 WORK_PLAN11（策略引擎）修复在真实复杂任务下有效
（对比旧 lru_ttl 首轮 7 次截断→human 已系统性消除）；4 任务全部首轮一次完成。

### 本 session 已完成（2026-08-14 续，WORK_PLAN13 深度迭代）

> 用户授权破坏性重构 + 激进推进，针对 08-14 深度分析发现的四项缺陷落地。

**改进**（4 项，全部真实复查验证）：
1. **语义门**：`ReviewerVerdict.issues[{severity:blocking|warning}]`；gate 拒绝"advance +
   blocking issue"（kv_failover-advance 类矛盾确定性拦截）；旧输出向后兼容。
2. **节点能力边界**：`Node.readonly`；官方模板 understand/read_code 只读 → 强制先设计后实现。
3. **运行时验证**：judge 节点 `verify` 宿主命令（`docker exec pytest`）→ 独立运行时证据进
   judge prompt；失败程序化注入 blocking issue 确定性拒绝 advance；`verify_enabled` 默认 false。
4. **上下文预算交接**：`context_handover_policy_json`（soft 询问自检预算+同会话续进 / hard 强制
   交接）；交接=新会话+真实交接文档（最近消息+节点+任务+汇报）+【上下文交接】开场。

**复查**（真实超长任务 `distributed_scheduler`，1127.5s / 1510 行 / 宿主 pytest 26/0）：
- 设计门**两次真实质询**（issue_pending→ask_developer，confidence 0.9）——只读 understand
  让设计门审未实现方案（对比旧 runs 一次通过）；
- test 门 **verify 宿主 pytest 证据**（rc=0）；wrap 节点**真实上下文交接**（usage 84%，
  新会话凭交接文档完成 wrap→complete）；
- **暴露并修复真实 bug**：drive 外部 supervisor T2 abort 会话后 workflow 死锁（外部 abort 哨兵
  → 诚实 BLOCK + `_own_abort` 保护 pause→resume 窗口）；reviewer 复杂判定散文回复未过纯 JSON
  门（extract_json 平衡括号鲁棒解析 + SYSTEM_PROMPT 强化 + max_reviewer_retries 2→3）。
- 基线 **506 passed 零回归**；归档 `tasks_docs/nightly_run_archive/20260814-wp13-recheck/`。

**遗留**：in-process watchdog 在真实 drive 下未先于外部 supervisor 触发（恢复路径 pause/resume/
fallback 在 drive 模式仍未实证）；`--meta` 元分析 / chaos 故障注入未接入复查套件（WORK_PLAN14
候选）。

### 本 session 已完成（2026-08-14 续，体系化重构 阶段 0）

> 用户授权彻底体系化重构（无历史包袱/无兼容修复/tricky）。宏观根因分析 + 阶段 0 落地，
> 蓝图 `tasks_docs/_regime_redesign.md`（临时工作簿，全阶段完成后并入 WORKLOG 并删除）。

| commit | 内容 |
|---|---|
| `989dac6` | **阶段 0：监督统一抽象收敛（W1/W2 根治 + 可观测性）**——drive 模式 `supervise_sessions=False`（会话级监督归 in-process watchdog，跟随 wait_sid 不失焦；进程外只留 T1/docker 重启 + 全局 deadline + meta 智能第二意见通道）；watchdog_fire 落共享 journal（修 W1 诊断盲区）；SseActivity 共享单一活性源（生命周期 try/finally 防泄漏）；CLI `--stall` 默认 None 仅显式覆盖 config；async argv 补 `--meta`/`--meta-model`；parallel/Drive 去死参数 stall_sec；测试 +6（512 passed）；文档同步（01_cli/subsystems/04 职责边界） |
| `5039528` | 文档同步：MAIN_TASKS 主线更新（阶段 1 待续）+ WORKLOG 决策沉淀 + HANDOVER 交接 |

**关键成果**：已知问题（W1–W6 + 交接硬编码 + 自定义缺失）收敛到 3 个体系化根因；
阶段 0 消除双看门狗竞态（W1）与 T2 失焦（W2），fire 落盘修诊断盲区；general 只读 review
（1 blocker + 4 warning + 4 nit）全处理；真实 worker drive 冒烟 124s complete 无回归；
基线 **512 passed 零回归**，已 commit（未 push）。
**遗留**：阶段 1（Regime 一等公民）为下一 session 主线（见 §8）；fallback 阶梯接线、
独立 supervisor 判定统一到 watchdog_policy、W3/W4/W5、交接硬编码、hooks/自定义 均为后续阶段。

### 本 session 已完成（2026-08-14 续，体系化重构 阶段 1a/1b/1d）

> 承接阶段 0，落地根因 A（运行制度碎片化）。蓝图同 `tasks_docs/_regime_redesign.md`。

| commit | 内容 |
|---|---|
| `bb73524` | **阶段 1：Regime 一等公民**——新增 `regime.py`（Regime 聚合对象 flow+roles+watchdog+handover + `compile_regime/validate_regime` 统一编译校验门 + `RegimeRegistry` 持久 store/原子热重载/失败保留当前）；`StatechartDriver.__init__` 接受可选 regime（制度权威源，阈值优先 settings）+ `from_regime`；`WorkflowUnit` context_policy 注入；`Drive` regime 参数；CLI `regime regime` 命令组（list/inspect/design/load/reload/rm）+ `run/drive --regime-name`（解析同一持久 store；修复 `--flow` 复用已解析 sm；run --async 转发）；permission regime 分类；死代码守卫接入 regime.py；文档（01_cli regime 命令表 + capabilities）；测试（test_regime.py 33 + test_cli regime 9，含 B1/B2/W1/W2 回归）；真实 worker `--regime-name` 冒烟 14s complete；552 passed 零回归 |
| `9bec61a` | 文档同步：阶段 1 完成状态 + 阶段 1c/1d 遗留明确（工作簿/MAIN_TASKS） |

**关键成果**：运行制度从 6 个碎片载体升为一等公民，拥有与 flow 相同的完整生命周期
（compile→deep_validate→preflight→hot-reload→version→permission→audit）；按名运行整制度
（`run/drive --regime-name`）真实可用；general 只读 review 两轮（2 blocker + 4 warning + nits
全处理）。**遗留**：阶段 1c（独立 supervisor 判定统一到 watchdog_policy，行为语义重设计）、
1d 补全（run-many/drive-many --regime-name、对话框制度入口）、阶段 2（扩展点/hooks/verify 白名单/
去交接硬编码）、阶段 3（W3/W4）、阶段 4（对话框意图级）。

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
conda run -n regime-driver regime job list|status <id>|logs <id> --json

# 命名运行制度（Regime 一等公民，阶段1；持久 store 默认 ~/.regime/regimes）
conda run -n regime-driver regime regime design <name> '<spec>' [--json]   # 内联设计并注册整制度(flow+roles+watchdog+handover)
conda run -n regime-driver regime regime load <spec.json> [--name] [--json]  # 文件加载
conda run -n regime-driver regime regime list|inspect <name> [--json]
conda run -n regime-driver regime regime reload <name> [--json]   # 原子热重载(失败保留当前)
conda run -n regime-driver regime regime rm <name> [--json]
conda run -n regime-driver regime run "<任务>" --regime-name <name>   # 按整制度运行
conda run -n regime-driver regime drive "<任务>" --regime-name <name> --container opencode-worker

# 夜间整合重跑（下一 session 主线；WORK_PLAN9 套件 + per-task 全量归档）
# 只跑一轮（4 复杂任务，不设时间上限）：bash ops/run_nightly.sh
# 限时循环：bash ops/run_nightly.sh --hours 2
# 单任务重跑：conda run -n regime-driver python ops/quality_run.py --tasks payment_ledger --root /tmp/r --clean-sessions
# 产出：quality-report.json（capability_coverage）+ tasks_docs/nightly_run_archive/<stamp>/（会话快照+工作区+切片）

# 可编程看门狗策略（WORK_PLAN11，config 或 REGIME_WATCHDOG_POLICY_JSON）
# watchdog_policy_json = '{"soft_sec":30,"soft_action":"interrupt","meta_gate_soft":true,"hard_sec":600}'
# auto_resume_sec = 30   # 被中断会话超此秒自动 RESUME 续接，仍无活性才 kill

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

# 部署 / 装配 / 卸载（分发与恢复）
conda run -n regime-driver regime setup [--target ~/.config/opencode] [--json]   # 引导安装
conda run -n regime-driver regime scaffold [--assistants] [--dry-run]             # 装配官方模板(含插件)
conda run -n regime-driver regime uninstall [--dry-run]                           # 按清单安全移除
conda run -n regime-driver regime doctor [--json]                                 # 自检(含部署完整性/环境检测)

# 任务注册表（收编 oc-task）
conda run -n regime-driver regime task list|status|logs|stop|clean <task-id> [--json]

# 进程外监督（收编 supervisor；宿主独立时钟 + docker 控制）
conda run -n regime-driver regime supervisor --base http://127.0.0.1:4097 --session <id> --container opencode-worker --reporter /tmp/sup.jsonl [--meta] [--once]

# 一键起栈（P1#3: worker/控制对话框容器构建+拉起+等健康）
ops/up.sh all          # worker+dialog-control
ops/up.sh dialog-control --rebuild   # 强制重建固化镜像再起

# 多 opencode 实例工作区隔离（P2: 每工作区一个实例, 无重复, 角色用session）
export REGIME_WORKSPACE_ROOT=~/.regime/workspaces   # 工作区根(默认)
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
REGIME_E2E=1 conda run -n regime-driver python -m pytest e2e_tests/test_e2e_worker.py -q

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
