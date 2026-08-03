# 调研：opencode 是否具备 thinking 运行超时守护能力

> 日期：2026-08-03
> 方法：opencode 1.18.11 官方文档 + GitHub `dev` 分支源码核对 + goal-plugin@latest 本地源码 + npm 生态检索。

## 结论

**opencode 及插件平台没有"thinking 语义级"的内置超时守护**（没有"思考多久无产出即判卡死"的现成看门狗）。
但具备三类可用能力：传输层超时（兜底）、事件级可观测（thinking 可被实时看到）、abort 干预（可中断卡死轮次）。
且插件可在进程内自建定时器看门狗（可靠性弱于进程外）。

## 1. opencode 内建超时（均为传输层，非 thinking 语义）

| 机制 | 位置 | 行为 |
|---|---|---|
| `provider.options.timeout`（默认 300000ms） | `src/provider/provider.ts:1754` | 单次 LLM 请求硬上限，`AbortSignal.timeout` 并入 fetch；abort 后该轮上下文丢失（`prompt.ts:1205` 标记 Aborted） |
| `provider.options.chunkTimeout`（默认 30000ms） | `provider.ts:37-83` `wrapSSE` | SSE 两次 chunk 间隔超时；**仅兜"完全静默"**，持续吐 reasoning chunk 不触发 |
| `headerTimeout`（默认 300s，openai） | `provider.ts:85-91` | 首字节超时 |
| `agent.steps`（maxSteps） | `session/prompt.ts:1178` | 步数上限，非时间 |

## 2. 插件平台能力边界（修正后的准确表述）

- **定时器可用**：插件寄宿在 Bun 进程，可 `setTimeout/setInterval`（goal-plugin 自身即用：wait 辅助 `goal-plugin.js:1965`、审计超时 `:3224`）。局限是**独立性**（宿主进程挂则插件定时器随之失效），而非能力缺失。
- **观测面**：thinking 期间每次 `reasoning-delta` 触发 `message.part.updated` 事件（`processor.ts:294-306` → `session.updatePart` → PartUpdated）。`session.status` 仅 `idle/busy/retry`（`schema/src/session-status-event.ts`），无 thinking 态；`busy` + 仅有 reasoning 更新 = thinking 循环的可观测签名。
- **干预面**：`POST /session/:id/abort`（或 SDK `client.session.abort()`）可中断卡死轮次 → 会话 idle → goal-plugin 恢复。

## 3. thinking 盲区根因（双保险同时失效）

1. **goal-plugin 主动豁免**：`latestHasThinkingTokens` 把 reasoning-only 轮次排除出 noProgress 停滞判定（`goal-plugin.js:4539-4554`）。
2. **supervisor.py T3 被动盲区**：`message_fingerprint` 把 reasoning 长度算进进展指纹（`supervisor.py:61-79`）→ thinking 循环时指纹持续变化，永不判停滞。
3. **预算只在 idle 检查**：goal-plugin 的 `maxDurationMs/maxTurns/maxTokens` 的 `stopReason` 仅 `goal-plugin.js:4481` 一处调用（idle 处理器内）→ thinking 卡死（永不 idle）时预算不触发。
4. 唯一带独立定时器的守卫是 completionAudit 的 `timeoutMs`（默认 120s，审计子会话），与主会话 thinking 无关。

## 4. 生态佐证

- `opencode-scheduler`：插件刻意把周期调度外包给 OS（launchd/systemd）+ 独立 supervisor 脚本，带 no-overlap + optional timeout → 印证"超时守护放进程外"是可靠做法。
- `opencode-timeout-continuer`：仅对传输层错误（408/429/502/503/504）重试，非 thinking 守护。

## 5. 对 M0 设计的启示

- thinking 语义级守护必须由"能看见 reasoning-delta 且能 abort"的一层承担 → 进程内插件最合适（秒级、无指纹盲区）。
- 进程级健康/重启/回退/期限 → 进程外 supervisor（独立性）。
- 物理兜底：显式配置 `provider.options.timeout` + `chunkTimeout` 纳入 `policy.json`。
