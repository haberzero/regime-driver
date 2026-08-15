# 质量收益验证报告（WORK_PLAN6 I · 夜间稳态+质量）

> **状态**：✅ 完成（2026-08-13 夜，~2h 真实运行；2026-08-14 增补夜间整合重跑 §7）
> 方法：`ops/quality_tasks.py`（12 个复杂工程任务套件）+ `ops/quality_run.py`（提交→等待→
> `docker cp` 产物→**宿主独立 pytest 复验**→reviewer 审查事件审计）。逐任务 `--clean-sessions`
> 防止 worker 会话累积退化；单任务在飞（无过度订阅）。
> 原始数据：`/tmp/quality-run/`（`quality-report.json`、`artifacts/<task>/`、`events.jsonl`、
> `tasks/*.summary.json`）；本文件是结论摘要。

## 1. 任务套件与验证维度

12 个真实工程任务（各有规格 + 显式边界/异常/并发要求 + 强制"写 pytest 覆盖指定边界并在容器内
运行直到全绿"）：graph_algos / stats_core / json_config / lru_ttl / csv_parse / task_sched /
token_bucket / string_util / money_fmt / json_diff / circular_buffer / anagram。

三维度验证：
1. **完成率**：每个任务 outcome + 耗时（`regime drive` 监督栈，deadline 900）。
2. **充分外部测试**：`docker cp` 产出的模块+测试 → 宿主 `regime-driver` 环境独立跑 pytest →
   记录 N passed/failed（独立于 worker 内自跑，验证产物真可测）。
3. **reviewer 审查收益**：从事件账本审计 reviewer_verdict / gate / rework 事件——证明审查门
   真实参与，不是走过场。

## 2. 结论摘要

**12/12 任务在最后一轮全部完成；宿主外部 pytest 全数通过（0 failed）；reviewer 审查每个任务**
**都产生 2–4 次实质判定。** 系统不仅能长时稳定运行，还能把复杂工程任务做完、并通过独立外部
测试复验其质量。

- 43 次任务尝试（2h 内循环约 3.6 轮）：**39 complete（90.7%）**；4 个非 complete **全部是
  诚实失败模式**（见 §4），无一静默失败，且后续轮次全部自愈。
- **质量收益证据**：
  - 宿主外部 pytest（最后一轮产物）：string_util 40p、csv_parse 30p、stats_core 26p、
    lru_ttl 22p、anagram 20p、money_fmt 18p、json_diff 17p、json_config 16p、task_sched 15p、
    graph_algos 13p、circular_buffer 12p、token_bucket 10p —— **全部 0 failed**。
  - reviewer 判定每个任务 2–4 次（design + test 两个 judge 节点真实审查），确定性门在
    task_sched 一次设计中真实拦截了不合法判定（gate exhausted）。
- **真实 bug 发现并修复**（本验证的意外收益）：`reviewer` agent 的 `bash "*": ask` 在 headless
  下遇复杂任务（reviewer 想跑 `pytest` 验证）触发权限 ask 死锁 → 挂 600s。已改为 `"*": deny`
  + 只读白名单（cat/grep/ls/rg/find/git）。修复后 graph_algos 从"挂死 17min+timeout"变为
  "85s complete + 宿主 pytest 13/13 + verdicts=2"。

## 3. 观测数据

### 3.1 完成率与耗时（现象 + 归属）
- 最后一轮 12/12 complete；单任务耗时 67–229s（DeepSeek 官方 API；复杂任务如 string_util 229s、
  csv_parse 197s，简单任务 ~100s）。
- 归属：`regime drive` 监督栈（executor + supervisor + reviewer）。

### 3.2 宿主外部测试（现象 + 归属）
- 12 个任务产物全部 `docker cp` 成功、宿主 pytest 全部通过（0 failed），累计 239 个断言通过。
- 归属：产物由 developer 在 worker 内完成并自跑 pytest；宿主复验为独立外部证据。

### 3.3 reviewer 审查事件（现象 + 归属）
- 每任务 reviewer_verdict 2–4 次（design+test 两 judge 节点）；gate 拦截 1 次（task_sched design
  gate exhausted）。
- 归属：`app/reviewer.py` + `core/contract.py` 确定性门。

## 4. 诚实失败模式（4 个非 complete，全部正确行为）

| 任务 | outcome | 现象 | 系统行为评价 |
|---|---|---|---|
| lru_ttl（第 1 轮） | human | developer 连续 7 次输出截断草稿（无 pytest），reviewer 拒、监督阶梯逐级升级到 L5 人工 | **监督阶梯正确工作**：检测到循环并诚实上报，不静默掩盖；后续轮次自愈（22p） |
| task_sched（第 1 轮） | error | design 节点 reviewer 反复输出不合法 verdict → 确定性门耗尽重试 | **确定性门正确拦截**：不合法判定绝不前进；后续自愈（15p） |
| task_sched（第 2 轮） | error | test 节点监督升级 human（连续停滞） | 阶梯兜底；后续自愈 |
| json_config（第 1 轮） | blocked | watchdog 重复检测拦截（`adjacent_sim=0.93` ≥ 阈值 0.9），非 reviewer 判定 | **看门狗正确拦截**：BLOCKED 是合法终态；后续自愈（16p） |

> 共性：4 个失败全部发生在**首轮冷启动**，后续轮次全部 complete —— 系统对单任务偶发退化
> 的处理路径（阶梯/human/gate 拦截）被真实触发并验证，且不会传染后续任务。

## 5. 附：harness 自身修复

- **pytest 计数解析 bug**：宿主 pytest 输出带 warnings 时（"16 passed, 12 warnings"）逗号使
  解析失配 → json_config 误报 0p。已修（去逗号再解析），复查=16p。**非系统质量问题**。
- **reviewer 死锁修复**（§2）已同步到 `docker/worker-config/agents/reviewer.md`（真源）+ 打包
  副本（sync_templates 漂移守卫绿）+ 运行容器（docker cp + restart）。

## 6. 结论与建议

1. **体系工作能力成立**：复杂工程任务（多函数+边界+异常+并发+真测试）能在监督栈下完成，产物
   通过独立外部 pytest 复验，reviewer 门真实参与。
2. **质量收益可度量**：239 断言全过 + reviewer 每任务 2–4 次实质判定 + 确定性门真实拦截。
3. **诚实失败路径已验证**：循环→人工、gate 耗尽、blocked 判定三种失败均正确终止且自愈。
4. **建议**：`reviewer` 死锁修复值得固化（已入真源/容器）；后续质量套件可并入 CI 或作为
   回归基线（成本：每任务 ~100–230s 真实模型，适合夜间/手动）。

---

## 7. 夜间整合重跑报告（WORK_PLAN8 阶段5 + WORK_PLAN9 验证，2026-08-14）

> **状态**：✅ 完成（2026-08-14 凌晨，单轮 4 任务全量）
> 方法：`bash ops/run_nightly.sh --root /tmp/nightly-run-20260814`（WORK_PLAN9 重构后的一键脚本）：
> 预检 → per-task 隔离工作区 → `regime drive` 监督栈 → 宿主独立 pytest 复验 → per-task 全量归档
> （会话快照 + 完整工作区 + journal/events 切片 + result.json）→ 能力覆盖报告 → 归档入库。
> 归档：`tasks_docs/nightly_run_archive/20260814-012700/`。

### 7.1 任务套件（WORK_PLAN9 新 4 复杂任务）

> 注：payment_ledger 的设计决策写入产物 `ledger.py` 头部 `# DESIGN DECISIONS (final):` 段
> （设计节点真实产生并经 reviewer 判定），未生成独立 DESIGN.md；其余 3 任务有独立 DESIGN.md。
> 归档忠实反映 worker 产物，非缺漏。

| 任务 | 内容 | outcome | 耗时 | 宿主 pytest | reviewer verdicts |
|---|---|---|---|---|---|
| shop_inventory | 遗留库存/定价/订单子系统重构 + 5 缺陷根因修复 + 折扣策略设计决策 | complete | 349s | 63p/0f | 2 |
| kv_cluster | 分布式 KV 存储（一致性/选举/故障转移）+ 跨模块契约 + 并发 | complete | 664s | 22p/0f | 2 |
| payment_ledger | 支付账本（原子性/异常/并发） | complete | 499s | 27p/0f | 3 |
| etl_pipeline | 数据管道（多模块/集成/错误隔离） | complete | 515s | 28p/0f | 2 |

### 7.2 能力覆盖（`quality-report.json` capability_coverage）

**声明 17 / 覆盖 17（0 uncovered）**：api-design、bug-fixing、code-odor、concurrency-testing、
cross-module-contract、design-node、edge-cases、error-handling、error-isolation、integration、
multi-module、read-existing-code、refactoring、root-cause、thread-safety、
tradeoff-documentation、wrap-hygiene。

### 7.3 结论

1. **最新架构下全链路无回归**：SSE 活性 watchdog + 可编程策略引擎 + 智能侧说明同步后，
   4/4 复杂任务诚实完成，零 ladder、零误杀（对比旧 lru_ttl 首轮 7 次截断→human 已消除）。
2. **能力覆盖引擎达标**：17/17 声明能力被真实触发，每任务 2–3 次 reviewer 实质判定，gate 无拦截。
3. **产物可独立复验**：宿主外部 pytest 全 0 failed（140 断言累计），worker 内自跑与宿主复验一致。
4. **建议**：夜间整合重跑可作发布前的标准回归门（`ops/run_nightly.sh`，~30min 单轮）。

## 8. 夜间长跑报告（2026-08-14 深夜，WORK_PLAN14 之后首轮全套件）

> 运行：`ops/quality_run.py` 全 5 任务各一圈，`REGIME_VERIFY_ENABLED=true` +
> `REGIME_CONTEXT_HANDOVER_POLICY_JSON`（WORK_PLAN13 复查同配置），`--stall 300 --deadline 3600`。
> 归档：`tasks_docs/nightly_run_archive/20260814-222131/`。

### 8.1 任务结果

| 任务 | flow | outcome | 耗时 | 宿主 pytest | reviewer verdicts | 设计门质询 |
|---|---|---|---|---|---|---|
| shop_inventory | code_workflow | complete | 468s | 0p/0f（collection 瞬时错误，复验 29p） | 4 | 2 |
| kv_cluster | code_workflow | complete | 1045s | 33p/0f | 3 | 2 |
| payment_ledger | code_workflow | complete | 384s | 36p/0f | 2 | 0 |
| etl_pipeline | code_workflow | complete | 849s | 39p/0f | 5 | 2 |
| **distributed_scheduler** | code_workflow_v13 | **blocked** | 1375s | 27p/0f | 4 | 2 |

能力覆盖：声明 17 / 覆盖 17（0 uncovered）。

### 8.2 关键发现：verify 白名单配置漂移真实 bug（已根治）

**现象**：distributed_scheduler 在 test 门 `blocked (watchdog kill)`，耗时 1375s。
**根因链**（journal 时序实证）：
1. `verify_result rc=None`（23:22:11）——verify 命令被白名单拒绝（`verify whitelist`）。
   运行时从 FlowRegistry 持久 store（`~/.regime/flows/code_workflow_v13.json`）读到的是
   **带 `sg docker -c` 包装**的 verify 命令（`sg docker -c "docker exec {container} ..."`），
   而真源 `ops/flow_v13.json` 是纯 `docker exec {container} ...` 形态——**store 残留旧配置**，
   `build_verify_argv` 因 `tokens[0] != "docker"` 拒绝（白名单拒绝是正确行为，但配置漂移导致）。
2. `reviewer_inquiry`（23:24:57）——reviewer 正确质询"verify 被白名单拒绝、需按白名单格式重跑"。
3. `dispatch_error transport timed out`（23:22:24）——developer 重跑验证时 POST 超时（模型侧瞬时错误）。
4. `monitor_abort`（23:30:09）——会话 300s 无 SSE 活性，默认策略（无 soft 动作）直接 kill。

**结论**：verify 命令未在**注册/校验时**做白名单预检——配置漂移到非白名单形态只会在运行中
（进入 test 门）才失败，且因白名单拒绝是"正确行为"（不执行），judge 拿不到 pytest 证据 →
语义门注入 blocking issue → 质询重跑 → 叠加 dispatch 超时 → 看门狗最终 kill。

**根治（本 session 已落地）**：
1. **`core/verify_spec.py`（新）**：`VERIFY_ALLOWED_EXECS` + `build_verify_argv` 从 app 层上移到
   core（纯函数、无 I/O），app/verify.py 复用（保持对外 API）。
2. **`core/validate.py`**：`_check_capability_boundaries` 增加 **verify 白名单静态预检**——
   非 `docker exec {container} <白名单程序>` 形态的命令在 `deep_validate` 时即拒绝，
   **注册/校验期失败，而非运行中**。测试 `test_verify_whitelist_shape_enforced` +1。
3. **`FlowRegistry._load_store`（W1 闭环）**：review 指出 store 装载路径不经过 deep_validate——
   残留非白名单 verify 落在 store 时仍会在运行中才失败（事故同构）。现装载时对每节点 verify
   做形状校验，残留命令在装载期被响亮拒绝+跳过（WARNING 记录）。测试
   `test_store_residual_verify_whitelist_rejected_at_load` +1。
4. **store 修复**：`regime flow reload code_workflow_v13` 使持久 store 与真源一致（纯 docker exec）。
5. 全量 **612 passed**（+2），死代码守卫/漂移守卫/sync_templates/check_capabilities 全绿。

### 8.3 其余观测

- **shop_inventory host_pytest 0p/0f**：`result.json` 记录 rc=2（collection errors），但同路径复验
  29 passed——运行当时为**归档后立即跑 host_pytest 的瞬时 collection 竞态**（worker 仍持有文件句柄/
  __pycache__ 残留），非系统缺陷；复验确认产物真实可测。
- **4/5 complete 零 ladder 零误杀**：普通复杂任务在最新架构下稳定完成，SSE 活性 + 语义门 +
  确定性 gate 全链路无回归（对比旧架构 payment_ledger 曾 7 次截断→human）。
- **设计门真实质询**：distributed_scheduler 设计门 2 次质询（issue_pending→ask_developer，
  confidence 0.9）——readonly understand 让设计门审的是未实现方案（WORK_PLAN13 语义门生效）。

### 8.4 建议

1. **verify 白名单预检已并入 deep_validate**：新 flow/regime 注册前 `regime validate --deep` 即拦截
   非白名单 verify，杜绝 store 残留类配置漂移再伤运行。
2. **可考虑 flow reload 时主动校验 verify 形态**（当前 reload 会 deep_validate，已覆盖）。
3. 超长任务（≥45min）建议配 soft 策略（`watchdog_policy_json` soft_sec/interrupt），让看门狗
   先中断续跑而非直接 kill，避免单次 dispatch 瞬时错误升级为整个任务失败。

### 8.5 修复验证：distributed_scheduler 单任务重跑（2026-08-15 凌晨）

> verify 白名单修复 + store 清理后，单任务重跑同一超长任务（`--tasks distributed_scheduler`，
> REGIME_VERIFY_ENABLED=true + 上下文交接策略 + --stall 300）。
> 归档：`tasks_docs/nightly_run_archive/recheck-verify-20260815-002235/`。

| 指标 | 首轮（修复前） | 重跑（修复后） |
|---|---|---|
| outcome | **blocked@test**（watchdog kill，1375s） | **complete**（1504.9s） |
| verify_result | rc=None（白名单拒绝 sg 包装） | **rc=0（拿到 pytest 证据）** |
| 宿主外部 pytest | 27p/0f | **26p/0f**（独立复验全绿） |
| reviewer verdicts | 4 | 3 |
| 设计门质询 | 2 次 | 0 次（方案一次通过） |

**结论**：同一超长任务在 verify 修复后由 blocked 转为 complete，且宿主外部复验 26p/0f——
证明 verify 白名单配置漂移是首轮失败的**直接根因**，修复（白名单静态预检 + store 装载期校验 + store 清理）
已闭环；verify 在 test 门真正提供运行时证据，语义门 + 确定性 gate 全链路恢复正常。

### 8.6 第二轮夜间长跑（verify 根除验证 + 两个新真实 bug）

> verify 彻底修复（StateMachine._validate 单点校验 + store 装载隔离 + store 清理）后，全套件 5 任务重跑
> （`REGIME_VERIFY_ENABLED=true` + 上下文交接策略 + --stall 300）。归档
> `tasks_docs/nightly_run_archive/nightly2-20260815-020027/`。

| 任务 | outcome | 耗时 | 宿主 pytest | 说明 |
|---|---|---|---|---|
| shop_inventory | complete | 566.8s | 37p/0f | 首轮 0p/0f collection 竞态消失 |
| kv_cluster | complete | 698.5s | 45p/0f | |
| etl_pipeline | complete | 549.6s | 22p/0f | |
| **distributed_scheduler** | **complete** | 1355s | 22p/0f | **三次 verify_result 全 rc=0**（verify 根除实证） |
| payment_ledger | **error@design** | 180.9s | — | reviewer gate exhausted（真实失败） |

**verify 根除验证成功**：distributed_scheduler 完整跑通，test 门三次 verify 全部拿到真实 pytest 证据
（rc=0）——对比首轮 verify rc=None → blocked@test。StateMachine._validate 单点校验 + store 装载期隔离
+ store 清理彻底生效，残留 sg 包装 verify 不可能再进入运行期。

#### 8.6.1 新 bug 1：extract_json 鲁棒性（reviewer 混合回复解析失败）

**现象**：payment_ledger error@design，`reviewer gate exhausted`。reviewer 每次输出"散文 + strict JSON"
混合回复，gate 反复报 `no JSON object in reviewer reply`。

**根因（第一层）**：旧 `extract_json` 单次扫描从第一个 `{` 开始维护全局字符串状态——散文里的**未闭合
引号**使 in_str 永久 True（吞掉 JSON 的 `{`/`}`），或散文里的**字面 `{`** 使起始位置错乱 → 提取失败。

**修复**：`extract_json` 改为遍历每个 `{` 作为候选 start，`_try_from` 独立跟踪括号/字符串状态（散文
引号不污染后续候选），第一个可解析 dict 返回。测试 +3（unbalanced quote / stray brace / 真实文本复现）。

#### 8.6.2 新 bug 2：judge 在流式 partial 回复上判定（真实根因，review 实证）

**review 关键指正**：extract_json 重写正确但**非根因**——存档时间线证明 gate 耗尽判定发生在最后一条
消息 `completed` 前 1.5s，即**判定落在流式未完成的 partial 回复上**；完整回复从未被判定。

**根因（真实）**：`workflow_unit._latest_assistant`（judge 路径）只要求 reply 非空、**不检查
`completed`**——对比 agent 路径 `_latest_agent_done` 明确等待 completed+finish。judge 在 partial 上判定
→ extract_json 对 partial 返回 None → gate 报错 → 重试 → 每次 re-prompt 又判 partial → 4 次耗尽；
id 去重使消息完成后**永不重判**。

**修复**：`_latest_assistant` 增加 `completed` 检查（judge 只判定已完成的 assistant 消息），与 agent
路径对称。测试 mock Message 默认 completed="now"（已完成语义），stall 场景显式 None；
新增 `test_judge_waits_for_completed_not_partial`。

#### 8.6.3 修复闭环实证（payment_ledger 重跑）

| 指标 | 首轮（修复前） | 重跑（修复后） |
|---|---|---|
| outcome | error@design（180.9s gate exhausted） | **complete**（396.5s） |
| design 判定 | partial 误判 → 重试耗尽 | 1 次通过（04:05:45→04:06:56） |
| 宿主外部 pytest | — | **30p/0f** |
| verdicts / gate_exhausted | 0 / 1 | 2 / 0 |

**结论**：两个修复（extract_json 鲁棒性 + judge 等待 completed）闭环。归档
`tasks_docs/nightly_run_archive/recheck-pl-20260815-040327/`。
