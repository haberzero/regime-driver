# 文档图例/图示方案评估（docs diagram assessment）

> 日期：2026-08-12 · 任务：用户要求以"初学者/普通读者视角 + 开发者视角"双视角，评估
> 对外文档是否/如何增加图例、图片形式内容，以及用 HTML/Markdown/JS 技术生成图例。
> 结论：**推荐 Mermaid 为主方案（文本描述、GitHub 原生渲染、MkDocs 插件化），保留 ASCII 于简单图；
> 否决静态 SVG / 内嵌 HTML / JS 交互图 / PlantUML / Graphviz。**
> 状态：**已实施（2026-08-12）**——7 张 Mermaid 图全部落地并通过 10.4.0 解析器校验；
> mkdocs 构建干净、407 测试零回归。实施记录见 TASK.md。

---

## 一、初学者/普通读者视角（评估）

### 1.1 新手真正需要的图（按价值排序）

| 图 | 读者痛点 | 现状 | 价值 |
|---|---|---|---|
| **一次任务的时序图**（你→对话框→体系→developer/reviewer→报告，审查者何时介入） | "跑一次到底发生什么、谁先谁后" | **缺失**（只有结构图，无时序） | ★★★★★ |
| **系统全景图** | "有哪些组件、谁连谁" | 已有 ASCII（index） | ★★★★ |
| **审查判定闭环**（通过/不通过/耗尽三分支） | "不过关到底会怎样" | 已有 ASCII 流程 | ★★★ |
| **监督纠正阶梯**（T1/T2/期限→L1-L5） | "卡死谁管、按什么顺序管" | 已有 ASCII | ★★★ |
| **设计流程的"成品示例图"**（03_design_flow） | "设计出来的流程长什么样" | 缺失（只有文字/表格） | ★★★★ |
| **舰队隔离图** | "并行任务怎么隔离" | 已有 ASCII | ★★★ |

### 1.2 新手读图偏好

- 简单、一屏看懂、有方向感；**不要 UML 级复杂度**（会吓退普通读者）。
- 图、文字、表格**不重复同一信息**（同一事实用一种形式）。
- **图例**（框/箭头/颜色的含义）常被忽略——现在部分 ASCII 图缺图例说明，这是比"缺图"更真实的缺口。
- 渲染一致性：读者可能从 GitHub 直接看 .md，也可能从站点看 HTML，**两端都要能读**。

### 1.3 结论（读者视角）

- 该加图：**任务时序图**（P0）、**设计流程成品图**（P0/P1）是最值得补的两个空白。
- 已有 ASCII 图多数够用，升级是"锦上添花"而非"必须"。
- 每个图必须配一句图例/说明，且不重复正文。

---

## 二、开发者视角（评估）

### 2.1 方案对比（决定性维度 = GitHub 原生渲染 + 可维护性）

| 方案 | GitHub 原生渲染 | MkDocs 渲染 | 可维护/可 diff | 构建依赖 | 结论 |
|---|---|---|---|---|---|
| **ASCII 码块（现状）** | ✅ 代码块 | ✅ 代码块 | ✅ 文本 | 零 | 保留于简单图 |
| **Mermaid 码块** | ✅（GitHub 2022-10 起原生支持 .md） | ✅ mermaid2 插件 | ✅ 文本可 diff，自动布局 | `pip install mkdocs-mermaid2-plugin` + 浏览器端 JS(CDN) | **主方案** |
| 内嵌 HTML/SVG | ⚠️ GitHub sanitize 不可靠 | ✅ | ⚠️ | 零 | 不推荐 |
| JS 交互图（ECharts 等） | ❌ 不执行 JS | ✅ | 依赖重 | 重 | 不推荐（文档站无需交互） |
| 静态 SVG 入库 | ✅ | ✅ | ⚠️ 改图需工具重新生成，易与文档漂移 | graphviz / mermaid-cli | 仅个别特殊场景 |
| PlantUML / Graphviz DOT | ❌ 不原生渲染 | ⚠️ 需插件/服务 | ✅ | 重 | **否决**（GitHub 端不可读） |

**决定性事实**：Mermaid 是唯一"文本描述 + GitHub 原生渲染 + MkDocs 可插件化"的方案。
PlantUML/Graphviz 在 GitHub 不渲染，内嵌 HTML/SVG 被 GitHub sanitize 不可靠，静态图必然漂移，
JS 交互在 GitHub 端不可见——它们全部出局。

### 2.2 已验证的技术事实（本机实测 2026-08-12）

1. `mkdocs-mermaid2-plugin 1.2.3` 与现站 readthedocs 主题 + 现有 extensions
   （`toc/tables/fenced_code/admonition`）兼容：在真实 `mkdocs.yml` 上临时挂载后构建干净。
2. 插件行为：` ```mermaid ` 块 → `<pre class="mermaid">` + 注入 mermaid.js → **浏览器运行时渲染**。
3. 默认从 `https://unpkg.com/mermaid@10.4.0/dist/mermaid.esm.min.mjs` 加载（外部 CDN）。
4. 插件可配：`version`（锁 mermaid 版本）、`javascript`（覆盖 JS URL → 可自托管消除 CDN 依赖）、
   `arguments`（mermaid init 参数，如 theme）。

### 2.3 需承担的成本/风险

| 项 | 说明 | 缓解 |
|---|---|---|
| CI docs.yml 加依赖 | `pip install mkdocs-mermaid2-plugin` | 一行；插件小 |
| 站点渲染依赖外网 CDN | 浏览器加载 unpkg；断网/内网时图空白 | 默认接受（GitHub Pages 本就联网，且 GitHub 端有原生渲染兜底）；可选 `javascript:` 自托管 |
| mermaid API 漂移 | 版本升级可能改语法 | 锁 `version: 10.x` |
| 页面加载变重 | 每个图浏览器渲染一次 | 克制：全站图控制在 ~10-12 张 |
| 双端差异 | GitHub 与站点的 mermaid 渲染引擎版本不同，极复杂图可能两端观感不一 | 用标准语法，避免边缘特性 |

### 2.4 最大优点（开发者视角）

**Mermaid 源码是文本**——可 diff、可 review、随文档改，不会像图片那样"文档改了图忘了"。
这正好满足 WRITING_GUIDE 的"概念归属唯一 + 文档与实现同步"纪律。

---

## 三、分级实施建议

### 3.1 用图分级策略

- **保留 ASCII**：简单链/线性流程/阶梯（≤5 实体、单向、无分支）——00 节点链、监督阶梯、
  事件时间线、01 quickstart 流程。
- **升级/新增 Mermaid**：
  - `docs/index.md`：系统全景图 → Mermaid `flowchart`（subgraph 分组：用户侧/体系侧/执行+监督）。
  - `docs/guide/00_god_dialog.md`：**新增"一次任务的时序图" `sequenceDiagram`**（最高价值，
    展示 你→对话框→体系→developer→reviewer→报告 的先后与审查介入点）。
  - `docs/guide/03_design_flow.md`：**新增"设计出的流程长什么样" `flowchart` 示例图**
    （agent/judge/tool/route 组合成一幅可读成品）。
  - `docs/architecture/02_statechart_network.md`：宪法↔工作流**信号协议 `sequenceDiagram`**
    （REPORT→检测→STOP→abort 时序）。
  - `docs/subsystems/04_supervisor.md`：监督循环 T1/T2/期限→阶梯 → `flowchart` 或 `sequenceDiagram`。
  - （可选）`docs/guide/06_fleet.md`、`00` 审查闭环分支图。
- **不引入**：截图（必然漂移、CI 无法验证）、JS 交互图（文档站不需要）、静态 SVG（漂移）。

### 3.2 优先级

- **P0（新手旅程，必做）**：00 任务时序图 + index 全景图升级 + 每图补"图例说明"。
- **P1（开发者理解，高价值）**：architecture/02 信号时序、subsystems/04_supervisor 监督时序。
- **P2（锦上添花）**：03_design_flow 成品示例图、06_fleet、00 审查闭环。
- **纪律**：WRITING_GUIDE 增补"图例纪律"小节（何时用图 / 图不重复文字 / 每图一句图例 /
  Mermaid 用法约束）。

### 3.3 实施路径（若执行）

1. `mkdocs.yml` 加 `mermaid2` 插件（`version: 10.4.0` 锁版）+ `.github/workflows/docs.yml`
   `pip install mkdocs-mermaid2-plugin`。
2. `docs/WRITING_GUIDE.md` 增补"图例纪律"。
3. 按 P0→P1→P2 逐图实施（每图：Mermaid 源码 + 一句图例 + 不重复正文）。
4. 本地 `mkdocs build` + 全量测试零回归 + general 只读 review + commit。
5. （可选，发布时）在 `docs/guide/07_release.md` 记录"站点依赖 unpkg CDN / 可自托管"说明。

---

## 四、总体结论

- **要加图**：最值得补的是"任务时序图"与"设计流程成品图"两个空白；已有 ASCII 图是底座，不需全换。
- **用什么技术**：**Mermaid 为主**（文本可 diff、GitHub 原生渲染、MkDocs 插件化，唯一全满足者）；
  ASCII 保留于简单图；其余方案（HTML 内嵌/JS 交互/静态 SVG/PlantUML/Graphviz）因 GitHub 端
  不可渲染或必然漂移而否决。
- **风险可控**：唯一新依赖是 docs 构建链的一个 pip 插件 + 站点浏览器端 CDN（有自托管选项）。
- **克制**：图服务于读者，不服务于展示；全站 ~10 张，每张配图例、不重复文字。
