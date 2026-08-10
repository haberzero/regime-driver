# regime-driver

> ## ⚠️ 开发中 / 未发布（Experimental · In Development）
>
> **本项目仍处于积极开发中的内部原型，尚未发布正式版本（尚无 v1.0，无稳定 API/CLI 契约）。**
>
> - **不稳定**：接口、命令、配置、行为可能随时不兼容地变更，**不保证向后兼容**。
> - **未完成**：长期运行耐久性（2h+ 无泄漏/能恢复）尚未完成系统化验证；CI 尚未在真实环境跑通；
>   仍有机器/模型/路径硬编码，未做通用化打包。
> - **未审计**：尚未经过外部安全审计；默认模型/供应商、端口、目录等为项目特定配置，需自行适配。
> - **自担风险**：使用本软件造成的任何直接/间接损失，作者概不负责（见下方 License 与免责声明）。
>
> 若你希望把本项目用于生产或作为依赖，请等待正式发布，或先联系维护者确认稳定性。
> 当前主要面向作者自用与研究探索。

---

L1 制度流程机器人（OA 系统）。把 `workflow-regime/` 制度化流程编译成状态机，驱动一个干净无插件的
opencode worker（L2）完成任务，并由只读审查者（L0）判定、确定性门把关。

**最终架构**：对等多状态机网络（宪法 = 无智能状态机 + 信号协议 + 根不变量运行时强制）。
详见 `docs/ARCHITECTURE-statechart-network.md`。

> **Status / 状态**
>
> - 测试：`333 passed`（含真实 worker E2E，`REGIME_E2E` 门控）。
> - 主线：内部核心功能（流程热编译/热加载、drive 一键栈、多实例隔离舰队等）已完成并检验；
>   发布就绪工作见 `WORK_PLAN6.md`。

## Install

```bash
conda create -n regime-driver python=3.12
conda run -n regime-driver pip install -e ".[dev]"
```

## 快速上手

```bash
# 校验 / 跑一个任务 / 并发跑多任务 / 校验判定 / 查 worker 健康 / 列会话
regime validate
regime run "实现 add(x,y) 并写 pytest" --base http://127.0.0.1:4097
regime run-many "实现 add(x,y)" "实现 mul(x,y)" --base http://127.0.0.1:4097
regime gate '{"node":"design","verdict":"advance","action":"advance","next_state":"implement","confidence":0.9,"reason":"ok"}'
regime status --base http://127.0.0.1:4097
regime sessions [--clean|--kill <id>] --base http://127.0.0.1:4097

# 上帝对话框（唯一对话控制面）
regime dialog --live --base http://127.0.0.1:4097
```

## 调试

```bash
# 离线确定性调试（无网络/无 LLM）
conda run -n regime-driver python ops/mock_feasibility.py
# 真实 E2E 逐操作计时
conda run -n regime-driver python ops/e2e_debug.py
```

## 测试

```bash
conda run -n regime-driver pytest
```

## 文档

导航与阅读顺序见 `docs/README.md`；书写准则见 `docs/WRITING_GUIDE.md`；已知限制见 `docs/KNOWN_LIMITS.md`。
改进工作清单见 `WORK_PLAN.md`。

## 配置与密钥

**配置文件**：见 `config.example.toml`（含全部字段说明）。用法：`regime run "任务" --config config.toml`。
优先级：默认值 < 配置文件 < 环境变量(`REGIME_<字段>`) < CLI 参数。

**环境变量覆盖**：任意 Settings 字段可用 `REGIME_<大写字段>` 覆盖，如 `REGIME_MODEL`、`REGIME_STALL_SEC`、`REGIME_POLL_SEC`。

**模型密钥**：默认模型 `my-opencode-go/deepseek-v4-flash`（OpenCode Go）。密钥零入库：
- worker/god 容器经 `OPENCODE_GO_API_KEY` env 注入（`ops/up.sh` 从 `~/.regime/keys/opencode-go.key` 读，或自设 env）。
- 交互式 opencode 经 `/connect` 存 `~/.local/share/opencode/auth.json`。
- 详见 `docs/DESIGN-usability.md`（主机 vs Docker、密钥安全、多场景安装）。自检：`regime doctor`。

## License 与免责声明

> **警告：本项目仍在开发中，未发布正式版本。** 作者按现状（AS-IS）提供本软件，不对其适用性、
> 正确性或安全性作任何明示或默示担保。因使用本软件（包括但不限于其驱动的 AI 模型输出、
> 自动执行的代码/命令）而产生的任何直接、间接、偶然或后果性损害，作者不承担责任。
> 本项目驱动真实 AI 模型与 Docker 容器、可自动执行代码——请务必在受控/隔离环境中使用，并自行审查其行为。

> 许可证：本项目**尚未选定最终开源许可证（License TBD）**。在明确标注许可证之前，代码仅供阅读与研究，
> 未经作者许可不得用于商业用途或对外分发。正式发布时将补充许可证文件（LICENSE）。