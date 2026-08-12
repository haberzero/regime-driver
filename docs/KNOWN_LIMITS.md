# 已知限制（KNOWN_LIMITS）

> 读者必读的边界清单。记录当前已知的未实现项、限制与行为边界，避免踩坑。
> 治理：本文件是"参考"类文档；新增限制时按 WRITING_GUIDE 记录"现象 + 影响 + 归属"。

## 面向外部 / 发布前须知（External-facing summary）

> **项目仍在开发中（未发布）。** 对外使用前请注意下列关键边界：
> - **无稳定契约**：CLI/API/配置可能破坏性变更，不保证向后兼容。
> - **耐久验证（2h+）**：2026-08-12 完成 2h 真实验证——零崩溃/停滞/重启，资源线性有界增长
>   （session 16→96、内存 +231MB、journal 3.4MB），worker 全程健康。结论与数据见
>   `docs/durability_report.md`。已知边界：**session 记录无法删除只能 abort**（见下方行为限制），
>   长期（多天）运行需定期清理或重建容器。
> - **GitHub 真实模型 E2E 已封存**：CI 内不再跑真实 worker E2E（2026-08-11 起，长期不列入计划；
>   需 `OPENCODE_GO_API_KEY` secret）。`tests/test_e2e_worker.py` 保留本地/手动可用（`REGIME_E2E=1`）。
> - **项目特定默认**：默认模型（`deepseek-api/deepseek-v4-flash`，DeepSeek 官方 API）、端口、目录为项目配置，需自行适配。
> - **依赖 opencode 内部 HTTP API**（`/event` SSE、session 端点），并锁定 opencode 1.18.x，
>   版本漂移可能破坏。**护栏**：`regime doctor` 会校验 worker 版本（major.minor 匹配才通过，
>   `check_version`）；`OpenCodeClient.health_info()`/`check_version()` 供程序化检测。
> - **强副作用**：驱动真实 AI 模型与 Docker，可自动执行代码——务必在隔离沙箱运行并审查其行为（见 `SECURITY.md`）。
> - **对外安装通道**：`pip install regime-driver` 后先 `regime scaffold` 生成官方模板，再 `regime doctor` 自检；
>   发布自检清单见 `docs/guide/06_release.md`。
> - 详细开发视角限制见下方各节（含"现象+影响+归属"）。

## 未实现 / 恒空项

> `data/regime.json` 现仅含 `code_workflow` 一个 flow。当前超时模型为 `default_deadline_sec`
> （每节点，settings）+ `global_deadline_sec`（整轮，constitution）。

## 行为限制

- **DELETE /session/{id} 返回 404**：当前 opencode-server（1.18.11）不支持删除远端 session。
  `regime sessions --clean`/`--kill` 只能 **abort**（释放 busy 状态），session 记录本身无法删除，
  会持续累积。归属：`infra/opencode.py` + `cli`。
- **session 状态不一致（message 404 + status busy）**：容器重启后，旧 session 的 `/session/{id}/message`
  可能 404，但 `/session/status` 仍报 busy（状态 map 残留）。受影响的 workflow 会在该会话上卡住
  （`_step_judge`/`_step_agent` 轮询死会话）。规避：`regime sessions --clean` 释放，或重启容器；
  严重时需重建容器（`docker rm -f` + `ops/up.sh`）。归属：opencode 1.18.11 行为 + `workflow_unit.py`。
- **god 助手 subagent 读外部目录需授权**：god 委派的 subagent（`analyst`/`advisor`）读 `/tmp` 等
  容器外/工作区外文件时，会触发 opencode 的 `external_directory` 权限 ask；headless 无交互时会挂起，
  需协作者应答 `POST /permission/{id}/reply`（`{"reply":"once"}`）。规避：把要分析的数据放进
  工作区（`/root/work`）内，或允许该目录。归属：opencode 权限系统 + `.opencode/agent/god.md`。
- **固化镜像依赖重建刷新**：`opencode-god`/`opencode-worker` 镜像把源码与配置烘焙进镜像；
  源码变更后未重建（`ops/up.sh` 会在 git HEAD 变化时自动重建，或 `--rebuild` 强制）会导致
  容器内运行旧包（如 god 无 `flow` 子命令、读不到新文档）。运行面已用 `-v` 挂载当前文档/插件，
  但 Python 包本体（`regime-driver`）仍以镜像内版本为准。归属：`docker/` + `ops/up.sh`。
- **HTTP 驱动 god 的权限策略**：god agent 的 bash 策略若为 `ask`，经 HTTP 程序化驱动（无交互方）会挂起
  （复合命令中任一子命令未放行即整体 ask）。当前 god.md 对 bash 设 `*: allow`，安全边界靠顶层
  `edit/write/apply_patch: deny` + 权限门禁（`--perm`），而非 bash ask。若改回 `ask`，需协作者轮询
  `GET /permission` 并 `POST /permission/{id}/reply`（`{"reply":"once"|"always"|"reject"}`）。
  详见 `docs/howto/god-window.md`。归属：`.opencode/agent/god.md` + opencode 权限系统。
- **免费 provider 有排队**：`opencode/deepseek-v4-flash-free` 基线慢 4–6 倍于官方
  `deepseek-api/deepseek-v4-flash`（官方有排队时更甚）。系统已默认用官方 API。归属：`infra/settings.py`。
- **`RolePolicy(transition_mode=ROTATE)` dataclass 遮蔽**：monkey 构造时字段默认值遮蔽类属性，
  测试已用构造参数规避。归属：`core/policy.py`。
- **`_run_talk` 硬编码**：上帝对话框 `talk` 固定 `agent="developer"` + 120s 超时，未参数化。
  归属：`app/god_dialog.py`。
- **async 作业注册表并发 lost-update 竞态**：`infra/jobs.py` 的 `registry.json` 是 load→patch→save 无
  文件锁；并发 `create`/`_refresh`（多进程同时写）可能丢记录。单 god agent 串行使用可接受；如需并发，
  应加文件锁或改为每作业独立文件 + 目录扫描。归属：`infra/jobs.py`。
- **插件工具经 shell 拼接命令**：`.opencode/plugins/regime-god.js` 把参数拼成字符串走 shell；job_id
  等由机器生成的内部 id 拼接，注入风险低，但新参数若来自外部输入需消毒。归属：`.opencode/plugins/regime-god.js`。
- **事件链路【可】接入（非限制，更正旧表述）**：上帝对话框/摄入层可经 `GET /event`（SSE 流）+
  插件 `event:` hook 实时接入事件链（`session.*`、`message.part.*`、`tool.execute.*`…），
  不必反复 CLI 轮询。真正的限制是"无**进程外独立**时钟"：缺事件→停滞检测必须靠独立时钟进程
   （supervisor），这是唯一无法靠事件链解决的问题。见 `subsystems/04_supervisor.md`。
   归属：`infra/opencode.py` + `app/reporter.py`。

## 边界（设计使然）

- **根不变量不可关**：I1 至少一 watchdog / I2 不可关 STOP 通道 / I3 元迭代上界，由 `Runtime.start`
  强制，用户自定义宪法也无法关闭。归属：`app/runtime_invariants.py`。
- **批次内 POST 序列化**：`_dispatch` await 前一 POST future，同一 workflow 内发派串行（防池饱和），
  多 workflow 并发不受影响。归属：`app/workflow_unit.py`。