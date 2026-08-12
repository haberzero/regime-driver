# 初学者读者批评报告（docs-reader critique）

> 日期：2026-08-12 · 视角：对项目一无所知的普通用户，按人类阅读习惯通读全部对外文档
> （README 中英 + docs/ 公开站）后提出的批评与建议。代码依据为同日核实的源码真相
> （标注 ✅ 者已确认与代码一致，标注 ⚠️ 者与代码不符）。本报告是实施改进的依据，
> 实施记录见 TASK.md。

---

## A. 读后不知所云（不清晰 / 语义不明）

1. **README / README.en 开篇用"L1 制度流程机器人（OA 系统）"**（README.md:19、
   README.en.md:15、reference/05_god_dialog_contract.md:12）。"L1/L2/L0" 与"OA 系统"
   是内部代号，普通读者（甚至多数工程师）不知道 L0/L1/L2 分层指什么。首页应先用
   一句话大白话讲"这是什么"，代号只允许出现在开发者文档。
   - 代码依据：L0/L1/L2 在代码中无定义（grep 无命中），纯历史叙事层代号。
2. **"上帝对话框"这一概念在被当作第一入口前没有解释"它是什么形态"**（docs/index.md:
   50-63 只画了对话流，没说对话框是"opencode 里的一个 agent（A 路）还是一个命令行
   REPL（B 路）"）。读者第一屏会疑惑"我要怎么开这个东西"。双路形态要尽早给一句。
   - 代码依据：GodDialogUnit.command 路由 status/monitor/watch/start/inspect/fleet/
     sessions/abort/reclaim/talk/design/flow/doctor（`src/regime_driver/app/god_dialog.py`）。
3. **"你只需要说话" vs 必须学短命令的矛盾**（docs/index.md:48、guide/00_god_dialog.md:
   17-19、55-60 与 guide/01_quickstart.md:29）。叙事反复强调"仍只是对话、不写流程"，
   但所有示例（`God> status`、`God> start code_workflow …`）用的都是短命令；
   `--live` 下自由文本才走 LLM 解释。读者会困惑：我到底要不要学命令？
   - 建议：00_god_dialog 明确两种模式（自然语言问/说 + 短命令），说明命令就是
     更快的方言，二者等价；quickstart 先自然语言后命令。
4. **`--perm run` 在快速开始突然出现**（guide/01_quickstart.md:9）：没解释为什么
   对话框启动任务要带权限、权限分几级。应在 01 给一行提示并指向 reference/04。
5. **用户文档里出现未定义的术语**：guide/00_god_dialog.md:49 "安全边界在确定性的
   后端（宪法 + 根不变量）"——对普通读者"宪法/根不变量"是黑话；index.md 多次用
   "状态机""确定性门"但只在 00 里浅提一次。至少应给一句人话定义（如"宪法=系统内置
   的安全看门狗，不可被关闭"），或把这些词移出用户文档。
   - 代码依据：`app/constitution_unit.py` + `app/runtime_invariants.py` 属实，但
     I1/I2/I3 概念对用户是噪音。
6. **"部署 2 起执行面 ops/up.sh"对 wheel 用户不可行**（README.md:60、README.en.md:67）：
   wheel 实测不含 `ops/up.sh`（zipfile 复核：up.sh in wheel=[]，docs 亦不在包内）。
   普通用户 `pip install regime-driver` 后拿到 `regime scaffold`，却没有任何"起 worker
   容器"的入口（`regime worker up` 需要镜像已存在；镜像要手动从 wheel 内 data/docker
   配方构建，但 scaffold 并不落这些配方）。README 把"一键起栈"当默认路径是在引导用户
   走进死路。
   - 建议：文档按"wheel 用户 → 主机模式（最简单）→ worker up（需自建镜像）"给三条
     真路径；up.sh 仅标注为"源码仓库路径"。这是文档层面的诚实修正（up.sh 打包属
     功能缺口，另记入 TASK 候选）。

## B. 需要更深入 / 更具体的流程与内部运行细节

1. **"监督器自动纠正"只有一句话**（docs/index.md:39、guide/02_capabilities.md §五）：
   读者会问——监督器怎么知道卡死？多久查一次？发现问题按什么顺序做？缺一张
   "监督纠正阶梯"图与"多久查一次"的数值。
   - 代码依据：`regime_driver/supervisor.py`（T1 健康、T2 停滞、deadline、阶梯
     nudge→abort→fallback→restart→human；`SessionWatch` 时间窗语义）。
2. **"审查不过关就不前进"——不过关时到底发生什么**（index.md:38、00 §4）：会重试吗？
   重试几次？耗尽后是终止还是人工？缺"审查判定闭环"小图（agent → judge → 确定性门 →
   advance/rework/exhausted）。
   - 代码依据：`core/contract.py` gate_reviewer_verdict + `max_reviewer_retries`
     （默认 2，config 文档有）。
3. **节点类型只对开发者讲**（reference/03_flow_spec.md §节点类型）：想设计流程的用户
   （guide/03_design_flow）只被告知"先实现再审查"，但 tool/route/gate 三种类型是什么、
   什么场景用，用户指南里没有一个直观示例。03_design_flow 应补"节点类型速览"。
   - 代码依据：`data/examples/verify_then_report.json`（tool+route 示例，随 wheel 打包，
     reference/03 已登记但 guide/03 未引）。
4. **session 的运维故事缺失**：用户被反复告知"每次运行都记录、session 会累积"，但
   只有 02_capabilities §八一句话带过 `sessions --cleanup`。缺"为什么累积/怎么清理/多久
   清一次"的实操指引（howto/run-many-sessions 已讲一部分，但没讲 cleanup 策略配置）。
   - 代码依据：`infra/opencode.py` DELETE /session 已核实真删（KNOWN_LIMITS 已更正）；
     `session_cleanup_policy` 配置项 + `regime sessions --cleanup`。
5. **reporter/journal/ledger 三词关系不清**：index/00/02 反复说"全程记录、可复盘"，
   但"报告日志（journal）/ 事件账本（ledger）/ 报告看板（report）"三者是什么关系、
   事件从 worker 怎么流到看板，没有一张链路图。建议在 00 §5 配事件链图并给出三词定义。
   - 代码依据：`app/reporter.py`（ingest/rollup/journal）+ `regime report`。

## C. 缺图像化 / 直观机制展示

1. **全站缺"系统总览图"**：你 ↔ 上帝对话框 → CLI → regime-driver（状态机/宪法/
   supervisor/reporter）→ worker 容器 → 模型，supervisor 在旁盯、reporter 在旁记。
   这是新手最需要的第一张图，应放 docs/index.md 顶部。
2. **缺"审查判定闭环"状态图**（agent → judge → 确定性门 → advance/rework/exhausted）。
3. **缺"监督纠正阶梯"图**（T1/T2/deadline → L1 nudge → L2 abort → L3 换模型 → L4 重启 → L5 人工）。
4. **缺"舰队/工作区隔离"示意图**（06_fleet）：三任务三容器三端口，产物互不污染。
5. **缺"事件账本复盘"时间线图**：node_enter → node_done → reviewer_verdict → advance → outcome。
6. **00 的 code_workflow 表格可配一张节点链图**（understand→read_code→design→implement→test→wrap）。
   - 实现取向：仓库既有风格是代码块 ASCII 图（index/00 已在用），零依赖、GitHub 与
     MkDocs 双端一致渲染；本批一律用 ASCII 图。Mermaid 留作远期候选（MkDocs 站点需
     mermaid2 插件，docs.yml 构建链需加依赖，暂不引入）。

## D. 冗长 / 重复（概念归属唯一，WRITING_GUIDE A.4）

1. **code_workflow 六行表在 guide/00 §2 与 guide/02 §二 完整重复**。保留 00（首次深入
   讲解），02 改为紧凑节点链图 + 指向 00。
2. **worker/god 分层表在 guide/00 "为什么 worker 是干净的执行器" 与 guide/05_setup §3
   几乎逐字重复**。概念归属 00；05_setup 只保留端口等操作信息 + 指向 00。
3. **CLI 契约三份近全量重复**：reference/01_cli.md（权威）、reference/05_god_dialog_
   contract.md §3（又一份全命令表）、CLI_REFERENCE.md（总览索引，可接受）。05 应瘦身为
   "对话框专属操作 + 指向 01_cli"，不再复制全量命令表；并修 §3 小节编号错乱（3.8 排在
   3.7 之前）。
4. **README "配置与密钥" 与 "部署 3 配模型密钥" 重复**（README.md:70-75 vs 127-131）：
   密钥注入细节出现两次。合并为一份，另一处指向之。
5. **guide/05_setup "核心概念" 与 guide/04_environment 部分重叠**（conda/pip/模型）：
   环境文档管"装环境"，setup 管"配模型与起服务"，重叠段收口到一处。

## E. 排布 / 目录 / 链接问题

1. **guide/ 出现两个 03 号**（03_design_flow.md 与 04_environment.md）——编号冲突，
   顺序断裂（03 之后接 04_setup 却前面已有 03 号）。重排为
   `00 god_dialog / 01 quickstart / 02 capabilities / 03 design_flow /
   04 environment / 05 setup / 06 fleet / 07 release`，同步 mkdocs.yml、
   docs/README.md、README 中英、guide 内互引。
2. **reference/05_god_dialog_contract.md 在 mkdocs nav 挂在"开发者指南"下**，但它是
   给对话框操作者（使用者）的手册，用户指南多处引用它。应移到"参考"区。
3. **guide/07_release.md（发布教程，维护者向）在用户指南目录里**、nav 又放在开发者区：
   编号与用户指南序列粘连。归属开发者（保持 nav 位置），编号随重排改 07 并明确标注
   维护者向。
4. **KNOWN_LIMITS 外部摘要引用内部文档**（docs/KNOWN_LIMITS.md:11 引
   `tasks_docs/durability_report.md`）：公开站文档引用内部过程产物，与 docs/README
   的"内部文档不进公开站"自相矛盾。改为"摘要 + 一句话"不引内部路径，或在仓库内可。
5. **reference/02_configuration 字段表与 config.example.toml 的一致性未声明**：
   应注明"配置字段以 `config.example.toml` 为唯一真源，本表为摘要"。
6. **docs/README（仓库导航）与 mkdocs nav 不完全对齐**：howto/god-window.md 只在 nav、
   不在 docs/README；reference/05 两边位置不一致。收口为同一映射。

## F. 小问题 / 错字 / 过时表述

1. **howto/god-dialog.md:39-44 列表缩进错乱**（` -` 前有多余空格，破坏列表渲染）。
2. **howto/run-many-sessions.md:26 "session 记录因 DELETE /session 不受支持而无法删除"**
   ⚠️ 过时——2026-08-12 已核实 opencode 1.18.11 `DELETE /session/{id}` 真删（KNOWN_LIMITS
   已更正）；`--clean` 现为 abort+delete。
3. **subsystems/09_testing_architecture.md**：`本 session（opencode host 1.18.15）`（过时
   版本号）、头部"状态：分析定案（待实施）"（已实施）、§6"关键设计决策（请确认）"
   （已定案）。改为当前状态表述。
4. **subsystems/07_god_dialog_carrier.md §3.6 "当前 regime CLI 契约未就绪：无 --json、无
   events --follow、无 session send"** ⚠️ 过时——均已实现（01_cli/05 契约已登记）。
5. **architecture/02_statechart_network.md** 自称"这是现行实现的架构真相"（:5），但
   §3 "现状"列写"1 个主 workflow（run() 顺序 while）"⚠️（现为 StatechartCluster 多
   workflow）、§5.2.1 引用已删除的 `Reviewer.judge`/`SegmentRunner`⚠️（代码 grep 仅存于
   本文档）。调整文档定位为"架构演进与状态机网络定案"，修正陈旧代码引用，并指向
   01_principles 为现行架构权威。
6. **guide/04_environment "你将会学到：区分项目运行时依赖与 dev 依赖分组"**：对普通
   用户过度内部。改为用户路径（pip install regime-driver + scaffold）优先，源码/开发
   路径（-e .[dev]）作为开发者小节。
7. **README "状态" 段引用 tasks_docs/WORK_PLAN7/6**（README.md:29-30）：对公众仓库首页
   是内部过程引用；可接受但建议压缩为"对外供给与耐久验证已完成"。

---

## 实施顺序（与 TASK 记录一致）

1. **结构重排**（E1/E2/E3）：guide 编号、05 契约归位、release 归属、nav 与 docs/README
   对齐（E6）。
2. **内容修订**（A1/A2/A3/A4/A5/A6 + B + F2-F5）：README 开篇去代号、双模式说明、
   术语定义、环境文档双路径、stale 表述更正。
3. **去重**（D1-D4）：code_workflow 表、worker/god 表、CLI 契约三份、README 密钥段。
4. **图解**（C1-C6）：index 全景图、审查闭环、监督阶梯、舰队图、事件链时间线、节点链。
5. **小修**（F1）：howto/god-dialog 缩进 + 命令补全（flow/doctor/fleet）。
6. **质量门**：`mkdocs build` 通过 + 全量测试零回归 + general agent 只读 review + commit。
