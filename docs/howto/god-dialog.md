# 如何：使用上帝对话框（A 路 opencode 载体 / B 路 regime dialog）

## 问题

想用一个对话面控制/监控所有 workflow，而不是记一堆 CLI 参数。

## 上帝对话框有两条路

- **A 路（推荐，opencode 作载体）**：一个 opencode `god` agent，通过 `regime` CLI 契约控制/监控系统。
  这是最接近"可对话的元系统"的形态；操作手册 `docs/reference/05_god_dialog_contract.md` + `docs/KNOWN_LIMITS.md`。
- **B 路（程序化 REPL）**：`regime dialog` 交互式提示符，是 CLI 的对话包装（对等状态机单元）。

两条路共用同一 CLI 契约与权限门禁（`--perm`）。

## A 路：opencode god agent（推荐）

1. 以 `god` agent 会话（`opencode` 提示中选 god，或配置为默认 primary）进入。
2. 它会先读 `../reference/05_god_dialog_contract.md` 与 `KNOWN_LIMITS.md`，然后照手册操作：
   - 监控：`regime status/sessions/events --json`
   - 运行：`regime run/run-many --json`（阻塞）或 `--async`（非阻塞作业）
   - 交互：`regime session <id> send/reply`
   - 校验：`regime validate/gate`
3. 写操作走统一权限门禁；god 默认持 `clean`，可降权只读。
4. 相关文件：`.opencode/agent/god.md`（agent 定义）、`.opencode/plugins/regime-god.js`（CLI 原生工具）。

## B 路：regime dialog REPL

```bash
regime dialog                         # 离线（MockClient），只读
regime dialog --live --base http://127.0.0.1:4097 --perm run   # 真实 worker + 写能力
```

在 `God>` 提示符下输入命令（中英文皆可）：
- `status` / `monitor node` — 实时快照 / 只查某字段
- `watch 10 watchdog` — 最近事件按主题
- `design myflow <JSON 或自然语言>` — 设计新 workflow
- `start myflow 做任务` — 非阻塞启动（可用设计流）
- `inspect god-1` — 查看某 workflow 黑板指标
- `flow list` — 列出已注册流程（`flow design` 同 `design`）
- `doctor` — 自检 worker/密钥/模板就绪
- `talk <session_id> 内容` — 与指定 opencode session 独立交互
- `sessions [busy]` — 列出 worker 会话及实时状态
- `abort <session_id> | abort --all` — 中止运行中会话（写）
- `reclaim <session_id> | reclaim --all` — 中止并删除（回收）会话（写）
- `help` — 全部命令；自由文本 — LLM 解释（`--live` 时）
- `quit` — 退出

## 预期结果

`start` 立即返回"已非阻塞启动 workflow：god-1"；随后 `status` 显示其 node/state 推进；自由文本异步返回 LLM 解释。
非阻塞提交也可直接用 `regime run ... --async` + `regime job status/list`。

## 说明

- **权限**：写操作（start/design/talk/run/send/clean）统一走 `--perm` 分级门禁；
  CLI 显式开启（如 `regime dialog --perm run`）；程序化构造 `GodDialogUnit` 默认只读（`allow_write=False`）。
- 对话框是**对等状态机单元**，共享同一 Runtime/黑板，故能实时看到 workflow 指标。见 `docs/subsystems/06_god_dialog.md`。
- 载体决策见 `docs/subsystems/07_god_dialog_carrier.md`。
