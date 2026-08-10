# 教程 02 · 第一次跑一个任务

本文带你跑第一个完整的 regime 任务。
面向配置好模型、想验证全流程的新用户。
覆盖校验、预检、运行与读结果。

## 你将会学到

- 用 `regime validate` 校验流程描述。
- 用 `regime preflight` 离线预跑。
- 用 `regime run` 跑一个真实任务并读结果。
- 用 `regime drive` 一键启动整套自驱动栈。

## 前置要求

- 已完成教程 00 与 01。
- worker 健康可用（`regime status` 通过）。
- 配置了有效模型密钥。

## 步骤

### 1. 校验 worker 健康

运行前先确认 worker 可用。
worker 不可用时，一切运行都会失败。

```bash
conda run -n regime-driver regime status --base http://127.0.0.1:4097
```

预期结果：输出 `{healthy: true, base: ...}`。
healthy 为 false 时，回到教程 01 排查 worker。

### 2. 校验流程描述

`regime validate` 检查流程描述是否合法。
`--deep` 增加语义深检，如角色、技能与可达性。

```bash
conda run -n regime-driver regime validate --deep
```

预期结果：输出流程名、节点数与 valid 提示。
校验失败会列出具体错误。

### 3. 离线预跑

`regime preflight` 用 MockClient 离线试跑整条流程。
它不连 worker、不烧模型，验证流程能否干净终止。
这能暴露静态检查漏掉的语义错误。

```bash
conda run -n regime-driver regime preflight --json
```

预期结果：输出 `{ok: true, outcome: complete, ...}`。
outcome 非 complete 时，先修复流程再跑真实任务。

### 4. 跑一个真实任务

`regime run` 在 worker 上跑任务直到完成。
命令阻塞，直到拿到最终结果。

```bash
conda run -n regime-driver regime run "实现 add(x,y) 并写 pytest" --base http://127.0.0.1:4097
```

预期结果：流程逐节点推进，最后打印 outcome。
`outcome` 取值有 `complete`、`error`、`timeout` 等。
complete 表示流程正常收尾。
非 complete 时看 `detail` 字段定位失败原因。

### 5. 读结果

`--json` 输出结构化结果，便于解析。

```bash
conda run -n regime-driver regime run "实现 add(x,y) 并写 pytest" --base http://127.0.0.1:4097 --json --ledger /tmp/tutorial.ledger.jsonl
```

预期结果：输出 `{outcome, end, detail, elapsed_sec}`。
`end` 是结束节点，`elapsed_sec` 是总耗时。
`--ledger` 写事件账本，可用 `regime events` 回看。

### 6. 用 `regime drive` 一键跑

`regime drive` 同时启动执行器与进程外 supervisor。
它还带 reporter 与可选元分析，构成完整自驱动栈。
对短任务可用 `regime run`，对需要监督的长任务用 `regime drive`。

```bash
conda run -n regime-driver regime drive "实现 add(x,y) 并写 pytest" --base http://127.0.0.1:4097 --reporter /tmp/rep.jsonl
```

预期结果：输出结果与 supervisor 判定。
用 `regime report /tmp/rep.jsonl` 查看汇报台账。

## 你现在能做什么

- 能校验并预检流程描述。
- 能在真实 worker 上跑任务并解读结果。
- 能用 `regime drive` 启动完整自驱动栈。

下一步进入教程 03，设计并热重载自定义流程。

## 深入指引

- 命令与判定语义：`../CLI_REFERENCE.md`
- 真实 E2E 与耗时解读：`../howto/run-e2e.md`
- 并发跑多任务：`../howto/run-many-sessions.md`
