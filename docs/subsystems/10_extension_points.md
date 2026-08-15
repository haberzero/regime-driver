# 统一扩展点模型

> 本文描述 regime-driver 的统一扩展面：用户经一个插件文件（`~/.regime/hooks.py`）注入
> 三类行为——生命周期 hooks、看门狗规则、确定性工具。面向需要自定义系统的开发者。
> 核心原则：**内核确定性门不可由用户代码触碰**；插件是策略层（声明式 + 插件式 Python），
> 只观察/通知/在界内定制，绝不覆盖确定性判定（根不变量 I1/I2/I3）。

---

## 1. 为什么需要统一扩展点

系统的"自定义"能力分散在三个互不协调的载体，各自存在注入与表达缺口：

| 载体 | 形态 | 问题 |
|---|---|---|
| 交接文档/提示词 | 硬编码 Python 字符串（`handover_policy.py`） | 无用户注入入口 |
| 看门狗规则 | 仅 JSON（`watchdog_policy_json`） | 无法用 Python 表达复杂谓词 |
| TOOL 工具 | 全局 `core.tools.register_tool` | 无统一入口/可见性 |

统一扩展点模型让三种注入从一个插件文件、一个 `register(registry)` 函数流入：

```python
# ~/.regime/hooks.py
def register(reg):
    @reg.hook("node_done")                  # 生命周期 hook（观察/通知/定制）
    def on_done(ctx): ...

    reg.register_rule("always-busy",        # 看门狗规则（纯谓词）
                      lambda ev: ev.busy(), "nudge", reason="demo")

    reg.register_tool("ping",               # 确定性工具（TOOL 节点）
                      lambda c, r, a: ToolResult(True, "pong"))
```

## 2. 注册表（`regime_driver.extensions.HookRegistry`）

| 方法 | 通道 | 消费方 |
|---|---|---|
| `register_hook(point, fn)` / `@reg.hook(point)` | 生命周期 hooks | workflow / watchdog 单元 `fire()` |
| `register_rule(name, predicate, action, *, meta, reason)` | 看门狗规则 | 驱动把 `registry.rules` 并入运行策略（`WatchdogPolicy.with_rules`） |
| `register_tool(name, fn)` | 确定性工具 | 委托既有 `core.tools` 注册表（内核 `run_tool` 读取） |
| `fire(point, **ctx)` | 运行 hooks | 收集返回值；hook 异常经 `on_error` 审计，绝不打断治理循环 |
| `reload()` / `summary()` | 热重载 / 对话框 `hook list` | 原子换新快照；运行中单元保持旧快照 |

**插件加载**（`load_user_hooks`）：默认 `~/.regime/hooks.py`（env `REGIME_HOOKS` 覆盖）。
- 文件不存在 → 空注册表（非错误）。
- 导入失败 / 缺 `register(reg)` → **响亮失败**（构造期 fail-fast，不做静默回退）。
- 运行期 hook 异常 → 记录 `hook_error` 审计事件，治理循环继续（同"坏规则不杀循环"契约）。

## 3. Hook 点（全审计）

| hook | 触发处 | 上下文（节选） | 是否可覆盖 |
|---|---|---|---|
| `node_enter` | `WorkflowUnit._enter_node` | `workflow node role type` | 否（观察） |
| `node_done` | `WorkflowUnit._step_agent`（agent 节点完成） | `workflow node role outcome report_len` | 否 |
| `transition` | `WorkflowUnit._apply_transition` | `workflow from to role decision` | 否 |
| `judge_verdict` | `WorkflowUnit._handle_verdict` | `workflow node verdict action confidence` | 否 |
| `stall` | `WatchdogUnit._emit_action/_emit_control` | `workflow session action reason` | 否 |
| `handover` | `WorkflowUnit._handover_package` | `workflow role node usage kind forced` | **是**：返回 `{"document":..,"opening":..}` 覆盖交接文档/提示词 |

**边界纪律**：观察类 hook 的返回值被忽略；只有 `handover` hook 可按契约返回覆盖。
任何 hook 都不能改变确定性判定（advance 门 / 看门狗动作 / gate），否则违反内核不变量。

## 4. 交接模板声明式化

`ContextHandoverPolicy` 增两个 `.format` 式模板字段（经 `context_handover_policy_json`）：

```json
{
  "soft_fraction": 0.5, "hard_fraction": 0.7,
  "min_continue_nodes": 2, "handover_keep_messages": 30,
  "document_template": "# 交接（{role}）\n任务：{task_context}\n当前节点：{node_id}\n最近消息：\n{messages}",
  "opening_template": "你接续 {role} 会话，处于 {node_id}。{document}"
}
```

优先级：**handover hook 覆盖 > 声明式模板 > 内置确定性构建器**。
`document_template` 字段：`{role} {node_id} {node_desc} {task_context} {report} {messages}`；
`opening_template` 字段：`{role} {node_id} {node_desc} {task_context} {document} {usage}`。

## 5. verify 白名单化（消 RCE）

`app/verify.py` 的 `run_verify` 不再接受宿主任意 shell 命令。命令**必须**是

```
docker exec {container} <白名单可执行程序> <参数...>
```

- 以 **argv 列表** 执行（`shell=False`，绝无宿主 shell 解释）——爆炸半径限定在 worker 容器内；
- 可执行程序白名单 `VERIFY_ALLOWED_EXECS`：`pytest / python / python3 / py / node / npm / npx / bash / sh`；
- docker 组过期时透明回退 `sg docker -c <shlex.join(校验后 argv)>`（宿主 shell 只见**再引号化的已校验 argv**，无法解释用户元字符）；
- 非白名单命令 → `verify whitelist: ...` 失败证据（响亮，非静默）。

## 6. 对话框 hook 装配

控制对话框新增 `hook` 命令：
- `hook list`（只读）——hooks/rules/tools 汇总 + 插件来源；
- `hook path`（只读）——插件路径；
- `hook reload`（写，权限门控）——重载 `~/.regime/hooks.py` 到新快照（运行中单元保持旧快照）。

## 7. 生命周期与权限

- hooks/规则/工具在**进程启动时**加载（CLI 各命令 / `regime dialog`）；对话框内 `hook reload` 热更新。
- `hook reload` 归写操作（`allow_write` 门禁，同 start/design/talk）。
- 新增插件文件不需要重装/重启 worker——它只影响宿主侧治理（驱动/看门狗在宿主源码上跑）。
