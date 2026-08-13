# 权限门禁

> 本文档描述 regime CLI 与控制对话框的权限等级、分类规则与配置天花板。
> 面向需要理解命令写操作边界的操作者。阅读前需了解 CLI 命令
> （见 `reference/01_cli.md`）与配置（见 `reference/02_configuration.md`）。

## 权限等级

**定位**：权限等级为有序枚举，等级从低到高。

| 等级 | 允许 |
|------|------|
| `read` | 只读：status / sessions-list / events / reply / validate / gate / job 查询 |
| `interact` | 上述 + `session send`（与 session 对话） |
| `run` | 上述 + `run` / `run-many`（启动流程，含异步 job） |
| `clean` | 上述 + `sessions --clean` / `--kill`（破坏性清理） |

**核心不变量**：

1. 等级全序：`read < interact < run < clean`。
2. 任何需要更高等级的操作被前置拒绝。
3. `clamp(held, ceiling)` 把自申报等级截断在配置天花板之下。

## 配置天花板

**定位**：`REGIME_PERMISSION_CEILING`（或配置 `permission_ceiling`）是写权限的硬上限。

**语义**：有效持有等级 = `clamp(--perm, ceiling)`。自申报 `--perm` 只能降低、
不能升高持有等级；即使传 `--perm clean`，若天花板更低也无效。天花板来自配置/环境，
故调用者无法自我提权。默认 `clean`。

**示例**：

```bash
export REGIME_PERMISSION_CEILING=run
regime run "任务" --perm clean   # 有效等级被截断为 run
```

## 命令分类

**定位**：`classify(argv)` 依据命令行返回所需等级，`require(held, needed)` 校验。

| 命令/子命令 | 所需等级 |
|-------------|----------|
| `status` / `events` / `validate` / `gate` / `preflight` / `report` / `job list/status` | read |
| `session send` | interact |
| `session reply` | read |
| `run` / `run-many` / `drive` / `drive-many` / `dialog` | run |
| `flow load` / `reload` / `rm` | run |
| `scaffold` / `setup` | run |
| `task submit` / `job create` | run |
| `task stop` / `clean` | clean |
| `sessions --clean` / `--kill` | clean |
| `supervisor` | clean |
| `uninstall` | clean |

**规则**：

1. 命令的首个非 flag 参数决定基础等级；子命令再细化。
2. `sessions` 带 `--clean`/`--kill` 升为 clean。
3. `flow` 的 load/reload/rm 升为 run，其余为 read。
4. `task` 的 stop/clean 升为 clean，submit 为 run，其余为 read。

## 控制对话框写门禁

**定位**：`DialogControlUnit.allow_write` 开关控制对话框的写能力。

**语义**：对话框默认只读，避免困惑的 LLM 回复触发副作用。`allow_write=False`
映射到 read；`allow_write=True` 映射到 clean（完全）。CLI 的 `dialog` 在有效持有
等级 `>= run` 时启用写能力，从不无条件启用。

**示例**：

```python
# 构造时显式授权写操作（否则 start/design/talk 被拒）
unit = DialogControlUnit(..., allow_write=True)
```
