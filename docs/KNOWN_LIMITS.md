# 已知限制（KNOWN_LIMITS）

> 读者必读的边界清单。记录当前已知的未实现项、限制与行为边界，避免踩坑。
> 治理：本文件是"参考"类文档；新增限制时按 WRITING_GUIDE 记录"现象 + 影响 + 归属"。

## 未实现 / 恒空项

- **`main_loop` flow 为死配置**：`data/regime.json` 中存在 `main_loop` 流程，但 `entry` 仅指向
  `code_workflow`，`main_loop` 不可达。`regime validate` 现已警告非入口不可达 flow。归属：`data/regime.json`。

> 注：旧架构的 `_deadline` 字段（meta 研判 deadline）已在 R1-R5 重构中随 monitor/meta_analyzer 删除，
> 不再存在。当前超时模型为 `default_deadline_sec`（每节点，settings）+ `global_deadline_sec`（整轮，constitution）。

## 行为限制

- **DELETE /session/{id} 返回 404**：当前 opencode-server（1.18.11）不支持删除远端 session。
  `regime sessions --clean`/`--kill` 只能 **abort**（释放 busy 状态），session 记录本身无法删除，
  会持续累积。归属：`infra/opencode.py` + `cli`。
- **免费 provider 有排队**：`opencode/deepseek-v4-flash-free` 基线慢 4–6 倍于官方
  `deepseek-api/deepseek-v4-flash`（官方有排队时更甚）。系统已默认用官方 API。归属：`infra/settings.py`。
- **`RolePolicy(transition_mode=ROTATE)` dataclass 遮蔽**：monkey 构造时字段默认值遮蔽类属性，
  测试已用构造参数规避。归属：`core/policy.py`。
- **`_run_talk` 硬编码**：上帝对话框 `talk` 固定 `agent="developer"` + 120s 超时，未参数化。
  归属：`app/god_dialog.py`。
- **async 作业注册表并发 lost-update 竞态**：`infra/jobs.py` 的 `registry.json` 是 load→patch→save 无
  文件锁；并发 `create`/`_refresh`（多进程同时写）可能丢记录。单 god agent 串行使用可接受；如需并发，
  应加文件锁或改为每作业独立文件 + 目录扫描。归属：`infra/jobs.py`。
- **插件工具经 shell 拼接命令**：`.opencode/plugins/regime-god.js` 把参数拼成字符串走 shell；job_id
  等由机器生成的内部 id 拼接，注入风险低，但新参数若来自外部输入需消毒。归属：`.opencode/plugins/regime-god.js`。

## 边界（设计使然）

- **根不变量不可关**：I1 至少一 watchdog / I2 不可关 STOP 通道 / I3 元迭代上界，由 `Runtime.start`
  强制，用户自定义宪法也无法关闭。归属：`app/runtime_invariants.py`。
- **批次内 POST 序列化**：`_dispatch` await 前一 POST future，同一 workflow 内发派串行（防池饱和），
  多 workflow 并发不受影响。归属：`app/workflow_unit.py`。