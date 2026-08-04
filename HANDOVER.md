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
- **git 管理**：`/home/haber/oc-meta` 已 `git init` + 两次提交。`.gitignore` 排除账本/日志/web/pid/任务运行态/`__pycache__`；密钥零入库（deepseek 密钥只从 opencode 全局配置读取）。
- **interface 供你接手**：直接 `python3 ops/oc-task.py submit "<工程任务>"` 即可跑真实工程任务；或先 `web start` 在浏览器盯状态。

## 5. 关键决策与踩坑记录

- **插件不能做周期/定时唤醒**：opencode 插件 hook 是事件驱动，无独立时钟契约 → 周期检测必须靠独立进程脚本。
- **控制面应是确定性脚本，而非又一个 agent**：agent 守不住固定流程；固定流程须用具体脚本硬约束。
- **"对话脚本"= 脚本是对象，对话是操控它的界面**（用户命名：上帝对话框）。用户要的是可对话、可自我修改、含反循环保证的元系统。
- **后台进程存活**：bash 工具每次调用结束会清掉后台进程，长驻服务须用独立进程/容器（`setsid`/docker 常驻）。
- **docker 权限**：`sg docker -c` 包装。

## 6. 当前运行状态

- `opencode-autopilot` 容器运行中（过渡层/对照，含 goal-plugin + stall-watchdog）。
- **`opencode-worker` 容器运行中（M-1 已上线）**：端口 4097，`opencode serve --pure` 无插件 headless。
  - 镜像 `opencode-worker:1.18.11`（基座 opencode-mvp + miniconda python 3.14 + 无插件）。
  - opencode.json 定义 `developer`(primary) + `reviewer`(只读 subagent)；无 plugin/command。
  - worker 挂载 `~/.local/share/opencode/auth.json` → 容器凭据；工作区 `workspaces/opencode-worker` → `/root/work`。
  - 已实测：/config（plugin:[]）、/agent、session 创建、deepseek-api LLM 调用（返回 WORKER_OK）全通。
- **stall-watchdog 插件已部署运行**（正式 thinkingStallSec=600s）；goal-plugin 同载（旧 autopilot 容器）。
- 测试工具保留：`ops/fake_reasoner.py`、`ops/fake_silent.py`（故障注入用，不常驻）。
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

## 8. 下一步（M0、M-1、M-2、M-3、安全监控已完成 → M-4 端到端试跑）

**M0 已全部完成 ✅**（stall-watchdog + supervisor v2 + oc-task + 故障矩阵 + git）。
**M-1 ✅**（worker 镜像，容器运行中）。**M-2 ✅**（正式工程包 `regime-driver`，见下）。**M-3 ✅**（审查者接入，见下）。**安全监控✅**（独立线程 + 紧急停止，见下）。

**当前方向**：`docs/DESIGN-regime-driver.md`（v0.3 定稿）——把 `workflow-regime/` 制度化流程编译成状态机，由固定代码机器人（L1）+ 审查者智能（L0）驱动**干净无插件**的开发者 opencode（L2）。里程碑 M-1 worker 镜像 → M-2 L1 骨架 → M-3 审查者接入 → M-4 端到端试跑。

**M-2 成果（正式工程版）**：`regime-driver` 包（`src/` 布局，PyPI 就绪）。架构 `docs/ARCHITECTURE-regime-driver.md`。分层 `cli → app → (core + infra)`；core 纯领域（确定性门/段协议/状态机/会话模型，无 I/O）、infra 封装 HTTP/文件（opencode 客户端/regime 加载/账本/配置）、app 编排（driver/session_manager/segment_runner）、cli 薄壳（typer+rich）。确定性门核对、`[WORK_DONE]` 段协议、5 轮会话检查均已接入。17 单测通过；端到端实测驱动 worker 完成两段（修复 bug + 新建模块），测试全绿。开发环境：conda `regime-driver`（py3.12）。

**M-3 成果（审查者接入）**：L0 审查者接入 L1 判定回路。新增 `app/reviewer.py`（严格 JSON 判定 + 带反馈重试 + 确定性门）、`infra/skill_loader.py`（按节点注入 skill）、`infra/task_control.py`（任务控制文档读写，节点完成写 WORKLOG）。节点名语义化（understand/read_code/design/implement/test/wrap）；审查者 prompt 明确列出合法 next_state；**advance 限定为后继节点**（杜绝回退/自环）；确定性门精确匹配。判定回路闭环：ask_developer（质询→开发者→回喂）、advance（用审查者目标推进）、request_context、abort/report_user。33 单测通过；端到端实测：审查者质询开发者→修复→advance→实现→测试验证→收尾，测试全绿，WORKLOG 正确写入。

**安全监控与紧急停止（M-4 前置加固）**：独立监控线程 `app/monitor.py` + 死循环检测 `core/repetition.py`（n-gram 重复率 + 相邻相似度，支持中文标点）。监控独立轮询所有 session 的 token/时间戳/消息文本，检测 ① 死循环 ② 卡死（busy 但 token 停滞 `stall_sec`）③ API 挂起；命中即 **abort + 终止 + 上报 blocked**。已实证 opencode 的 `POST /session/{id}/abort` 真正打断 token 生成（58/138 → 58/157 冻结），是**与人类多次 ESC 等价的紧急停止**。修复 `session_status` 读取 bug（busy 状态在 `/session/status` 全局 map）。end-to-end 实测：卡死 → monitor 检测 → abort → blocked 上报。45 单测通过。

阅读顺序：`DESIGN-regime-driver.md` → `ARCHITECTURE-regime-driver.md` → `workflow-regime/README.md`。

**关键决策速记**：审查者常驻 session（只读不可跑命令，可要求开发者跑）；开发者 1 个 session（基础 AGENTS.md，不自查，段末 `[WORK_DONE]` 汇报，5 轮里程碑询问）；JSON 契约与镜像自主决定；全局状态清单（开发者不可见）单独设计；**安全监控独立线程 + 确定性 abort 紧急停止**。

### 里程碑进度

| M | 内容 | 状态 |
|---|---|---|
| **M-1** | worker 镜像 `opencode-worker:1.18.11`（miniconda + 无插件 + reviewer 只读 agent） | ✅ **完成，容器运行中** |
| **M-2** | L1 骨架：正式工程包 `regime-driver`（src/ 布局 + 确定性门 + session 管理 + 5 轮检查 + `[WORK_DONE]` 段协议） | ✅ **完成，17 单测 + 端到端全绿** |
| **M-3** | 审查者接入：skill 注入 + 判定回路 + 硬规则 + 任务控制文档 | ✅ **完成，33 单测 + 端到端全绿** |
| **M-4 前置** | 安全监控与紧急停止（独立监控线程 + 死循环检测 + abort 上报） | ✅ **完成，45 单测 + 端到端全绿** |
| M-4 | 试跑真实工程任务 + 故障演练 | 待实施 |

**待办**：M-4 端到端试跑；全局状态清单设计（P1）；审查者 session 轮换细则（P2）；多开发者 session（P3）。

## 9. 命令速查

```bash
# 提交一个自主任务（任务注册表模型，每任务独立 supervisor 进程）
python3 /home/haber/oc-meta/ops/oc-task.py submit "<goal>" [--deadline 30]

# 任务控制（接收接口，人类与 opencode 共用）
python3 /home/haber/oc-meta/ops/oc-task.py list
python3 /home/haber/oc-meta/ops/oc-task.py status <task-id>
python3 /home/haber/oc-meta/ops/oc-task.py logs <task-id>
python3 /home/haber/oc-meta/ops/oc-task.py stop <task-id>
python3 /home/haber/oc-meta/ops/oc-task.py clean <task-id>

# 只读网页状态页（可选，起停可控）
python3 /home/haber/oc-meta/ops/oc-task.py web start   # http://127.0.0.1:8721
python3 /home/haber/oc-meta/ops/oc-task.py web stop

# 单次直接运行（不走任务注册表）
bash /home/haber/oc-meta/ops/oc-run.sh '<goal>' [deadline_min]

# 容器状态 / 重启
sg docker -c 'docker ps --filter name=opencode-autopilot'
sg docker -c 'docker restart opencode-autopilot'

# worker 容器 (M-1, 无插件开发执行面)
sg docker -c 'docker ps --filter name=opencode-worker'
sg docker -c 'docker restart opencode-worker'
# worker 镜像构建 (改动 docker/worker-config 后需重建)
sg docker -c 'docker build -f docker/Dockerfile.worker -t opencode-worker:1.18.11 .'
# worker API 冒烟测试
curl -s http://127.0.0.1:4097/config

# regime-driver (M-2/M-3, 正式工程包, cli->app->core/infra 分层)
# 开发环境: conda 环境 regime-driver (python 3.12); 本地已 pip install -e .
source ~/miniconda3/etc/profile.d/conda.sh
conda run -n regime-driver regime validate          # 校验状态机
conda run -n regime-driver regime gate '<verdict-json>'  # 校验审查者判定
conda run -n regime-driver regime status --base http://127.0.0.1:4097
conda run -n regime-driver regime run "<任务上下文>" --base http://127.0.0.1:4097 --ledger /tmp/regime-ledger.jsonl
conda run -n regime-driver python -m pytest           # 单测 (45 项)

# 核心代码: src/regime_driver/{core,infra,app,cli}; 架构: docs/ARCHITECTURE-regime-driver.md
# 状态机: src/regime_driver/data/regime.json (打包默认); 开发期可 --regime 指定
# 审查者判定: app/reviewer.py (严格 JSON + 重试反馈 + 确定性门); skill 注入: infra/skill_loader.py
# 任务控制文档: infra/task_control.py (WORKLOG/NEXT_STEPS/PENDING_TASKS), 由 --task-control-dir 启用
# 安全监控: app/monitor.py (独立线程) + core/repetition.py (死循环检测)
#   监控参数: --monitor-enabled/--monitor-poll-sec/--stall-sec/--on-stall (abort|report_user|none)
#   监控由 config 或 env: REGIME_MONITOR_ENABLED/REGIME_POLL_SEC/REGIME_STALL_SEC 等控制

# 看账本（插件 + supervisor 共享）
tail -f /home/haber/oc-meta/ops/run-ledger.jsonl

# 启动监督器（旧方式，容器内；现已被 oc-task 取代）
docker exec -d opencode-autopilot python3 /root/control/supervisor.py \
  --goal "<目标>" --policy /root/control/policy.json
```