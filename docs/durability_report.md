# 长期运行耐久性报告（WORK_PLAN6 I · L1）

> **状态**：✅ 完成（2026-08-12，2h 真实验证）
> 方法：`ops/durability.py` 对真实 worker（`opencode-worker:1.18.11`，DeepSeek 官方 API）持续提交
> `regime drive --async` 受监督任务（executor + supervisor 同栈），每 ~150s 提交一个、每 60s 采样
> 资源并审计事件账本。原始数据在 `/tmp/durability-run/`（`samples.jsonl` 事件+资源采样、
> `events.jsonl` 事件账本、`tasks/*.summary.json` 每任务结果）；本文件是结论摘要。

## 1. 运行环境

| 项 | 值 |
|---|---|
| 目标时长 | 2h（7200s，实测 7205s） |
| 任务节奏 | 每 ~150s 提交一个新 drive（同 worker，无隔离） |
| 采样间隔 | 60s（113 个样本） |
| worker | `opencode-worker:1.18.11`，`http://127.0.0.1:4097` |
| 模型 | `deepseek-api/deepseek-v4-flash`（DeepSeek 官方 API） |
| 任务 | 38 个真实受监督 drive（`--deadline 600`） |
| 观测面 | session 数 / journal+ledger 增长 / task 注册表 / worker 内存 / ladder 事件 |

## 2. 结论摘要

**2h 连续真实运行：零崩溃、零停滞、零重启、零升级（ladder 事件 = 0）。**
session 累积与 journal/内存随运行线性增长（有界、可预测），未出现无界泄漏或不可恢复状态；
worker 全程健康。**系统"2h+ 能持续运行"的核心声明成立**。

唯一未达标项是**任务完成率 27/38**——但 11 个未完成全部是 `supervisor=timeout`（命中每任务
600s deadline），根因是**本验证自身的过度订阅**（同 worker 每 150s 发一个、而单任务可长达 10min，
积压使并发 busy 从 4 涨到 13），**非系统故障**——supervisor 正确执行了 deadline 并产出干净的
`error/timeout` 结果。

## 3. 观测数据（现象 + 影响 + 归属）

### 3.1 任务完成率与纠正阶梯（现象 + 归属）
- 38 个 drive：**27 complete（42–106s）+ 11 timeout（609–621s，全部命中 600s deadline）**。
- **ladder 事件 = 0**（无 stall/restart/abort/escalate/gave_up）——纠正阶梯未被触发，系统无需干预。
- timeout 任务经 supervisor 正确产出 `error/timeout` outcome，事件账本与任务注册表一致（27+11=38）。
- 归属：`supervisor`（deadline 执行正确）；`ops/durability.py`（验证配置过度订阅）。

### 3.2 session 累积（现象 + 影响 + 归属）
- session 数 16 → 96（+80，~每任务 +2.1）。
- **session 记录无法删除（opencode 1.18.11 DELETE /session 404，KNOWN_LIMITS），只能 abort**；
  已 abort 的 session 仍占用注册表条目，故随运行线性累积。
- 影响：可观测、有界、每 session 固定成本；本机 96 session 未影响 worker 健康。
- 归属：`infra/opencode.py`（client）+ opencode 1.18.11 行为。

### 3.3 journal / ledger 增长（现象 + 归属）
- 报告 journal 10KB → 3.4MB（约每 drive +90KB，线性）。
- 事件 ledger 10KB → 约 1.4MB。
- 影响：可预测线性增长；`regime report --prune` 可用于长期收尾（L2）。
- 归属：`app/reporter.py` / `infra/ledger.py`。

### 3.4 worker 内存（现象 + 归属）
- 466MiB → 697MiB（+231MB / 2h，约 1.9MB/min，线性）。
- 影响：与 session 累积相关（每 session 上下文驻留）；2h +231MB 在 123GB 主机上可忽略，
  但**无上限的 session 累积最终会推到 worker 资源边界**——需 L2 治理（回收/重启）。
- 归属：opencode worker 进程（session 上下文驻留）。

### 3.5 stall / 恢复（现象 + 归属）
- **0 stall、0 恢复**：所有任务要么完成、要么被 deadline 干净终止。本次未触发 T2 stall 检测
  （任务短，未达 stall 阈值）——stall→恢复路径未被本次负载压测。
- 归属：无（未触发）；stall 恢复的能力由既有真实 E2E（test_e2e_worker）覆盖。

## 4. 结论与建议

### 4.1 "2h+ 能持续运行"声明
**成立**：零崩溃/停滞/重启，资源线性有界增长，worker 全程健康。可对外如实陈述
"2h 连续真实运行稳定，资源有界增长"（并附本报告）。

### 4.2 完成率修正（本次 27/38 的解释）
- 11 个 timeout 是验证配置造成的积压（单 worker 过度订阅），不是系统缺陷。
- 建议后续耐久基线：**限制并发**（`--task-sec` 大于单任务耗时，或 `drive-many --workers N`），
  观察"稳态无积压"下的完成率；预计接近 100%。

### 4.3 L2 资源治理（下一步）
- session 累积是**真实、有界、但无上限**的运营成本：长期（多天）运行需定期
  `regime sessions --clean`（abort 旧 session）或重建容器。建议把"session 数 > N 则提示清理"
  纳入 `regime doctor` 或 supervisor 周期动作。
  **✅ 已落地（2026-08-12）**：`regime doctor` 增 "session hygiene" 检查（worker 健康时统计 session
  数，≥100 警告"abort/rebuild advised"），阈值 `session_hygiene_threshold` 可配。
- journal/ledger 线性增长：长跑脚本收尾建议自动 `regime report --prune`（L2 待接入）。

### 4.4 C3 参数校准
- 单任务完成 42–106s（DeepSeek 官方 API），默认 `default_deadline_sec=600` 对单任务充裕。
- 并发积压下任务显著变慢（busy 13 时出现 timeout）——**并发上限比单任务超时更敏感**。
- repetition 阈值 0.40 本验证无 repetition 误报（无 ladder 事件），无需调整。
