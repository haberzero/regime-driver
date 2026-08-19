# 已知限制（KNOWN_LIMITS）

> 读者必读的边界清单。记录当前已知的未实现项、限制与行为边界，避免踩坑。
> 治理：本文件是"参考"类文档；新增限制时按 WRITING_GUIDE 记录"现象 + 影响 + 归属"。

## 面向外部 / 发布前须知（External-facing summary）

> **项目仍在开发中（未发布）。** 对外使用前请注意下列关键边界：
> - **无稳定契约**：CLI/API/配置可能破坏性变更，不保证向后兼容。
> - **耐久边界（2h+）**：长时间（2h+）真实运行资源线性有界增长（session/内存/journal 随运行时长线性累积），无崩溃/停滞/重启；已知边界：**session 记录累积**
>   （见下方行为限制），长期（多天）运行可用 `regime sessions --cleanup` 清理或重建容器。
> - **GitHub 真实模型 E2E 长期不列入计划**：CI 内不跑真实 worker E2E（需 `OPENCODE_GO_API_KEY` secret）。
>   `e2e_tests/test_e2e_worker.py` 保留本地/手动可用（`REGIME_E2E=1`）。
> - **项目特定默认**：默认模型（`deepseek-api/deepseek-v4-flash`，DeepSeek 官方 API）、端口、目录为项目配置，需自行适配。
> - **依赖 opencode 内部 HTTP API**（`/event` SSE、session 端点），并锁定 opencode 1.18.x，
>   版本漂移可能破坏。**护栏**：`regime doctor` 会校验 worker 版本（major.minor 匹配才通过，
>   `check_version`）；`OpenCodeClient.health_info()`/`check_version()` 供程序化检测。
> - **强副作用**：驱动真实 AI 模型与 Docker，可自动执行代码——务必在隔离沙箱运行并审查其行为（见 `SECURITY.md`）。
> - **对外安装通道**：`pip install regime-driver` 后先 `regime scaffold` 生成官方模板，再 `regime doctor` 自检；
>   发布自检清单见 `docs/guide/07_release.md`。
> - 详细开发视角限制见下方各节（含"现象+影响+归属"）。

## 未实现 / 恒空项

> `data/regime.json` 现仅含 `code_workflow` 一个 flow。超时模型：`default_deadline_sec`
> （每节点，settings）+ `global_deadline_sec`（整轮，watchdog）——**默认均关闭**（fail-safe，
> 与 settings 默认 None 一致），停滞兜底由 SSE 活性看门狗承担；显式传 `--deadline` 才启用墙钟杀。

## 行为限制

- **DELETE /session/{id} 真正删除**：opencode 1.18.11 的 `DELETE /session/{id}` **真正删除**
  session 记录（从 `GET /session` 列表与 `/session/status` map 都移除，含 idle 与 busy 会话）。
  `regime sessions --clean` 可真正清理累积 session。自动清理策略配置 `session_cleanup_policy`
  （可自定义，参考模型非强制）。归属：`infra/opencode.py` + `cli`。
- **session 状态不一致（message 404 + status busy）**：容器重启后，旧 session 的 `/session/{id}/message`
  可能 404，但 `/session/status` 仍报 busy（状态 map 残留）。受影响的 workflow 会在该会话上卡住
  （`_step_judge`/`_step_agent` 轮询死会话）。规避：`regime sessions --clean`（现可真正删除）或重启容器；
  严重时需重建容器（`docker rm -f` + `ops/up.sh`）。归属：opencode 1.18.11 行为 + `workflow_unit.py`。
- **控制对话框助手 subagent 读外部目录需授权**：dialog-control 委派的 subagent（`analyst`/`advisor`）读 `/tmp` 等
  容器外/工作区外文件时，会触发 opencode 的 `external_directory` 权限 ask；headless 无交互时会挂起，
  需协作者应答 `POST /permission/{id}/reply`（`{"reply":"once"}`）。规避：把要分析的数据放进
  工作区（`/root/work`）内，或允许该目录。归属：opencode 权限系统 + `.opencode/agent/dialog-control.md`。
- **固化镜像依赖重建刷新**：`opencode-dialog-control`/`opencode-worker` 镜像把源码与配置烘焙进镜像；
  源码变更后未重建（`ops/up.sh` 会在 git HEAD 变化时自动重建，或 `--rebuild` 强制）会导致
  容器内运行旧包（如 dialog-control 无 `flow` 子命令、读不到新文档）。运行面已用 `-v` 挂载当前文档/插件，
  但 Python 包本体（`regime-driver`）仍以镜像内版本为准。归属：`docker/` + `ops/up.sh`。
- **HTTP 驱动对话面的权限策略**：dialog-control agent 的 bash 策略若为 `ask`，经 HTTP 程序化驱动（无交互方）会挂起
  （复合命令中任一子命令未放行即整体 ask）。当前 dialog-control.md 对 bash 设 `*: allow`，安全边界靠顶层
  `edit/write/apply_patch: deny` + 权限门禁（`--perm`），不用 bash ask。若改回 `ask`，需协作者轮询
  `GET /permission` 并 `POST /permission/{id}/reply`（`{"reply":"once"|"always"|"reject"}`）。
  归属：`.opencode/agent/dialog-control.md` + opencode 权限系统。
- **免费 provider 有排队**：`opencode/deepseek-v4-flash-free` 基线慢 4–6 倍于官方
  `deepseek-api/deepseek-v4-flash`（官方有排队时更甚）。系统已默认用官方 API。归属：`infra/settings.py`。
- **`RolePolicy(transition_mode=ROTATE)` dataclass 遮蔽**：monkey 构造时字段默认值遮蔽类属性，
  测试已用构造参数规避。归属：`core/policy.py`。
- **`_run_talk` 硬编码**：控制对话框 `talk` 固定 `agent="developer"` + 120s 超时，未参数化。
  归属：`app/dialog_control.py`。
- **async 作业注册表并发 lost-update 竞态**：`infra/jobs.py` 的 `registry.json` 是 load→patch→save 无
  文件锁；并发 `create`/`_refresh`（多进程同时写）可能丢记录。单 dialog-control agent 串行使用可接受；如需并发，
  应加文件锁或改为每作业独立文件 + 目录扫描。归属：`infra/jobs.py`。
- **插件工具经 shell 拼接命令**：`.opencode/plugins/regime-dialog-control.js` 把参数拼成字符串走 shell；job_id
  等由机器生成的内部 id 拼接，注入风险低，但新参数若来自外部输入需消毒。归属：`.opencode/plugins/regime-dialog-control.js`。
- **事件链路可接入**：控制对话框/摄入层可经 `GET /event`（SSE 流）+
  插件 `event:` hook 实时接入事件链（`session.*`、`message.part.*`、`tool.execute.*`…）。
  **停滞判定统一以 SSE 事件流为活性信号**（`SseActivity` 采集器 → watchdog/supervisor），
  token 计数（`session_tokens`）是 step 粒度记账（processor.ts step-finish 才落账 + 异步
  projector 写库），单步长思考期间恒 0，不能作为流式活性信号。归属：`app/sse_activity.py` +
  `app/watchdog_unit.py` + `supervisor.py`。
- **工具执行期间可能误杀**：会话 busy 但长时间跑工具（如 >`stall_sec` 的长
  bash 命令）且无 LLM delta 时，SSE 活性链看不到进展 → 判停滞并 abort（破坏性）。默认
  `stall_sec=180`（长思考/突发流式裕量）；如需覆盖，提高 `stall_sec` 或把
  `session.status`/`tool.*` 事件计入活性。归属：`app/watchdog_unit.py`。
- **可编程看门狗策略**：watchdog 是策略引擎（`app/watchdog_policy.py`）——
  `SessionEvidence`（SSE活性/消息时间戳/节点/首次busy/系统时间/paused）+ 可注入 `Rule`
  判定（多规则取最严重）+ 动作阶梯 `Ladder`（nudge→interrupt(PAUSE)→resume→fallback→kill，
  per-session 隔离 + fire-once）。PAUSE 中断当前生成并冻结节点推进，RESUME 恢复（agent 注入
  "继续"/judge 重发判定），paused 超 `auto_resume_sec` 自动 RESUME 再兜底 kill。`meta=True`
  规则交由智能判定确认（仅作第二意见，不推翻已执行的确定性动作）。默认 `default_policy` 保持经典行为。
- **两级 watchdog 职责边界**：drive 模式的会话级停滞判定**只归进程内策略看门狗**
  （`supervise_sessions=False`，外部 supervisor 不做会话 T2，避免双头竞态）；进程外 supervisor
  只保留 T1 健康/容器重启 + 全局期限 + 元分析。独立 `regime supervisor` 命令才有完整外部
  会话阶梯。归属：`app/watchdog_unit.py` + `supervisor.py` + `drive.py`。
- **测试套件分层**：单元/功能正确性套件在 `tests/`（`testpaths=["tests"]`，
   纯 mock 无真实 LLM/Docker）；真实 worker E2E 独立于 `e2e_tests/test_e2e_worker.py`
   （`REGIME_E2E=1` 显式运行）。`pytest` 默认不收集 E2E。归属：`pyproject.toml` + `e2e_tests/`。
- **能力地图与实现一致性**：`docs/capabilities.md` 是能力索引单点真理；`ops/check_capabilities.py`
  做交叉核对（CLI 命令/skills/covers 标签），改动能力时应同步文档或跑脚本确认。归属：
  `ops/check_capabilities.py` + `docs/capabilities.md`。
- **默认流程 skill 注入**：`code_workflow` 的 design/test（reviewer judge）挂 design-philosophy/code-review，
   implement/wrap（developer）挂 developer-quality。agent 节点 skill 缺失会 fail-fast（配置错误）。
  归属：`data/regime.json` + `app/workflow_unit.py`。
- **verify 阻塞混合循环**：`verify` 是同步 `subprocess.run`（上限
  `min(request_timeout, 300)`s），执行期间 workflow 混合循环无法 drain STOP/PAUSE——兜底 kill
  或 deadline 期间若恰在跑 verify 会等它结束。已白名单化到 docker-exec（argv、无宿主 shell）。
  归属：`app/verify.py` + `app/workflow_unit.py`。
- **瞬时消息错误不误杀**：`_latest_abort` 只把真正 abort（`MessageAbortedError`
  类 / completed 无 finish 形状）判死会话；瞬时错误（模型 HTTP/限流）继续轮询（受节点
  `default_deadline_sec` 上限）+ 记 `message_transient_error` 审计。边界：若瞬时错误恰带
  completed 且 finish=None 的 abort 形状，无法与真 abort 区分（判 abort）。归属：
  `infra/opencode.py` + `app/workflow_unit.py`。

## 边界（设计使然）

- **根不变量不可关**：I1 至少一 watchdog / I2 不可关 STOP 通道 / I3 元迭代上界，由 `Runtime.start`
  强制，用户自定义看门狗也无法关闭。归属：`app/runtime_invariants.py`。
- **批次内 POST 序列化**：`_dispatch` await 前一 POST future，同一 workflow 内发派串行（防池饱和），
  多 workflow 并发不受影响。归属：`app/workflow_unit.py`。