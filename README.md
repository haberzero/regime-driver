# regime-driver

**English**: [README.en.md](./README.en.md)

> ## ⚠️ 开发中（Experimental · In Development）
>
> **本项目处于积极开发中，尚未发布正式 v1.0（无稳定 API/CLI 契约保证）。**
>
> - **稳定性**：核心已通过 2h+ 长期运行验证（零崩溃/停滞/重启，资源有界增长）与复杂工程任务套件验证；
>   但接口/命令/配置仍可能变更，**不保证向后兼容**。
> - **安全**：尚未经过外部安全审计；默认模型/供应商、端口、目录为项目特定配置，需自行适配。
> - **自担风险**：使用本软件造成的任何直接/间接损失，作者概不负责（见下方 License 与免责声明）。
>
> 若你希望把本项目用于生产或作为依赖，请等待正式发布，或先联系维护者确认稳定性。

---

把"你给 opencode 下达的元指令"变成**一定会被执行的确定性流程**。

regime-driver 把一条**流程**（一组有顺序、有角色的步骤：理解 → 设计 → 实现 → 审查 → 收尾）
编译成状态机，在一个干净无插件的 opencode worker 上**逐节点驱动**执行：

- **干活与审查分离**：干活节点由开发者会话完成，审查节点由只读审查者判定；
- **确定性门把关**：审查判定过不了确定性门就**不前进**；
- **进程外监督**：独立时钟盯着卡死/停滞/超时，按阶梯自动纠正；
- **全程可复盘**：每次运行都写入事件账本与报告日志。

**核心架构**：对等多状态机网络（看门狗 = 无智能状态机 + 信号协议 + 根不变量运行时强制）。
详见 `docs/architecture/02_statechart_network.md`。

> **Status / 状态**
>
> - 测试：全量 `python -m pytest` 绿（覆盖 71%+）；真实 worker E2E 本地可用（`REGIME_E2E=1`，CI 内已封存）。
> - 主线：内部核心功能（流程热编译/热加载、drive 一键栈、多实例隔离并行任务、控制对话框）已完成；
>   对外供给就绪（模板进包 / scaffold / 单一真源 / 发布文档）与长期耐久验证（2h+ 真实运行）均已完成。

## Install

```bash
conda create -n regime-driver python=3.12
conda run -n regime-driver pip install -e ".[dev]"
```

> pip 安装（wheel）自带用户运行所需的官方模板（agents/skills/插件/dialog-control agent/
> opencode.json/regime.json/config），无需 clone 仓库即可 `regime scaffold` / `regime setup`
> 一键装配；`regime doctor` 自检就绪度。Docker 资产（Dockerfile/镜像配置）经 GitHub 仓库提供，
> 不进 pip wheel（分发原则见 `docs/architecture/04_distribution_blueprint.md`）。

## 部署

### 1. 获取官方模板（一次）

```bash
# 从包内模板生成 ~/.config/opencode/{agents,skills}（幂等；--dry-run 预览）
regime scaffold
# 需要控制对话框助手 subagent（analyst/advisor/reviewer）时
regime scaffold --assistants
# 自检：worker 健康 / 模型密钥 / 模板就绪
regime doctor
```

### 2. 起执行面

**容器化（推荐）**——一键构建 + 拉起 worker/控制对话框容器并等健康：

```bash
ops/up.sh all          # worker + dialog-control
ops/up.sh dialog-control --rebuild   # 强制重建固化镜像
```

> `ops/up.sh` 是源码仓库脚本（wheel 安装不含）。仅 wheel 安装的用户用**主机模式**
> （推荐，opencode 作主对话框 + worker）直接驱动本机 opencode；需要容器化时 clone
> 仓库（Dockerfile 在仓库 `docker/`，不进 wheel）。

**主机模式**——直接驱动宿主机上的 opencode 服务：

```bash
regime run "任务" --base http://<主机 opencode 端口>
```

### 3. 配模型密钥

- worker/控制对话框容器经 `DEEPSEEK_API_KEY` env 注入（`ops/up.sh` 从 `~/.regime/keys/deepseek.key` 读，或自设
  env）；密钥零入库。
- 交互式 opencode 经 `/connect` 存 `~/.local/share/opencode/auth.json`。
- 详见 `docs/guide/04_environment.md`。

## 快速上手

```bash
# 校验 / 跑一个任务 / 并发跑多任务 / 校验判定 / 查 worker 健康 / 列会话
regime validate
regime run "实现 add(x,y) 并写 pytest" --base http://127.0.0.1:4097
regime run-many "实现 add(x,y)" "实现 mul(x,y)" --base http://127.0.0.1:4097
regime gate '{"node":"design","verdict":"advance","action":"advance","next_state":"implement","confidence":0.9,"reason":"ok"}'
regime status --base http://127.0.0.1:4097
regime sessions [--clean|--kill <id>] --base http://127.0.0.1:4097

# 控制对话框（唯一对话控制面）
regime dialog --live --base http://127.0.0.1:4097
```

## 调试

```bash
# 离线确定性试跑（无网络/无 LLM）：同一驱动代码跑 MockClient，验证流程能终止
regime preflight [--fault stall|delay] --json
# 真实 worker E2E（需 worker 容器健康 + REGIME_E2E=1）
REGIME_E2E=1 conda run -n regime-driver python -m pytest tests/test_e2e_worker.py -q
# 事件 / 宏观台账
regime events --ledger /tmp/rep.jsonl
regime report --journal /tmp/rep.jsonl
```

## 测试

```bash
conda run -n regime-driver pytest
```

## 文档

文档站（MkDocs + Read the Docs 主题）：`https://haberzero.github.io/regime-driver/`，从门户首页
（是什么/为什么/功能/能做到什么）开始，按读者分层：**用户指南**（跑任务/配置/操作）、**参考**（CLI/
配置/流程规格）、**开发者指南**（架构/子系统/如何开发）。仓库内导航见 `docs/README.md`；
已知限制见 `docs/KNOWN_LIMITS.md`；书写准则见 `docs/WRITING_GUIDE.md`。
当前主线规划见 `tasks_docs/WORK_PLAN8.md`。
> 注：`docs-ref/` 是另一项目文档的参考副本，**不入库**（gitignore），仅作写作参考。
> 供 agent 执行的内部配置（skills / 控制对话框助手 / workflow-regime 模板）是机器专用内容，不进文档站。

## 配置与密钥

**配置文件**：见 `config.example.toml`（含全部字段说明）。用法：`regime run "任务" --config config.toml`。
优先级：默认值 < 配置文件 < 环境变量(`REGIME_<字段>`) < CLI 参数。

**环境变量覆盖**：任意 Settings 字段可用 `REGIME_<大写字段>` 覆盖，如 `REGIME_MODEL`、`REGIME_STALL_SEC`、`REGIME_POLL_SEC`。

**模型密钥**：默认模型 `deepseek-api/deepseek-v4-flash`（DeepSeek 官方 API），密钥零入库。
配置方式见上方"部署 3 配模型密钥"与 `docs/guide/04_environment.md`；自检：`regime doctor`。

## License 与免责声明

> **警告：本项目仍在开发中，未发布正式版本。** 作者按现状（AS-IS）提供本软件，不对其适用性、
> 正确性或安全性作任何明示或默示担保。因使用本软件（包括但不限于其驱动的 AI 模型输出、
> 自动执行的代码/命令）而产生的任何直接、间接、偶然或后果性损害，作者不承担责任。
> 本项目驱动真实 AI 模型与 Docker 容器、可自动执行代码——请务必在受控/隔离环境中使用，并自行审查其行为。

> 许可证：**MIT License**（Copyright © 2026 Nan Shi 施楠），见根目录 `LICENSE`。
> 注意：软件仍处于开发中，MIT 许可授予的是"按现状使用"的权利，**不构成任何可用性/正确性/安全性担保**
> （见上方免责声明）。