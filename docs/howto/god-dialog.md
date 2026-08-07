# 如何：使用上帝对话框（regime dialog）

## 问题

想用一个对话面控制/监控所有 workflow，而不是记一堆 CLI 参数。

## 步骤

1. 启动（离线默认，无 LLM；`--live` 用真实 worker + LLM 解释）：

   ```bash
   regime dialog                      # 离线（MockClient）
   regime dialog --live --base http://127.0.0.1:4097   # 真实 worker
   ```

2. 在 `God>` 提示符下输入命令（中英文皆可）：
   - `status` / `monitor node` — 实时快照 / 只查某字段
   - `watch 10 watchdog` — 最近事件按主题
   - `design myflow <JSON 或自然语言>` — 设计新 workflow
   - `start myflow 做任务` — 非阻塞启动（可用设计流）
   - `inspect god-1` — 查看某 workflow 黑板指标
   - `talk <session_id> 内容` — 与指定 opencode session 独立交互
   - `help` — 全部命令；自由文本 — LLM 解释（`--live` 时）
   - `quit` — 退出

## 预期结果

`start` 立即返回"已非阻塞启动 workflow：god-1"；随后 `status` 显示其 node/state 推进；自由文本异步返回 LLM 解释。

## 说明

- 写操作（start/design/talk）CLI 已显式开启（`allow_write=True`）；程序化构造 `GodDialogUnit` 默认只读。
- 对话框是**对等状态机单元**，共享同一 Runtime/黑板，故能实时看到 workflow 指标。见 `docs/DESIGN-god-dialog.md`。