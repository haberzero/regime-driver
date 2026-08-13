# 测试架构

> 本文描述测试架构与职责定位：**开发 session ≠ 被测对象**；E2E / 控制对话框验证走 HTTP 程序化驱动，
> 而非交互式 TUI。澄清各 opencode 实例（worker/dialog-control/开发）的运行位置与驱动方式。面向测试维护者。

---

## 1. 必须分清的两条正交轴（混淆的根源）

过去"opencode run 挂起"造成的混乱，根因是**把两条轴混为一谈**：

```
轴 A — 组件职责（这是"谁"）
  开发 session / worker 执行器 / 监督器 / 控制对话框 / 报告总线

轴 B — 运行位置与驱动方式（这是"在哪、怎么用"）
  宿主进程 / 容器进程 / 浏览器 web / 交互式 TUI / HTTP 程序化 / CLI 子进程
```

**同一个 opencode 二进制**可以承担不同角色（交互式开发窗 vs 无头执行器），也可以在不同位置运行。
"opencode run 挂起"只说明**交互式 TUI 驱动**在本 shell 不可用；**它完全不阻塞 HTTP 程序化驱动**。

---

## 2. 概念职责定位（谁干什么）

| 概念 | 职责 | 运行位置 | 驱动方式 | 是否被测对象 |
|---|---|---|---|---|
| **本 session（开发宿主）** | **开发**：写 regime-driver 代码与测试 | 宿主 | 交互 | **否**（开发，不被测） |
| **worker 容器（opencode 1.18.11, `serve --pure`）** | **执行器**：干任务节点，无插件干净环境 | 容器（4097） | HTTP | **是**（E2E 在此执行） |
| **regime-driver（Python 包）** | **编排/驱动**：编译流程、驱动 worker、监督、报告 | 宿主或容器 | CLI / 被调用 | 单元测 + E2E 驱动者 |
| **regime-driver.supervisor** | **进程外监督**：独立时钟、T1/T2、deadline、纠正阶梯 | 宿主或容器 | CLI | 真实验证 |
| **控制对话框 A 路（dialog-control agent）** | **控制面**：经 regime CLI 控制/监控全系统 | 容器内 opencode（web/HTTP） | HTTP（非 TUI） | **E2E 目标** |
| **控制对话框 B 路（`regime dialog`）** | 程序化控制面（REPL） | 宿主 | 交互 REPL / 被调用 | 单元测 |
| **Reporter / `regime report`** | 可观测性 | 宿主/容器 | CLI | 用 |

**职责唯一原则**：
- **只有 regime-driver 驱动 worker 做任务**；worker 绝不直接接人类/控制对话框。
- **控制对话框只控制**（经 regime CLI），绝不直接干任务。
- **本 session 只开发**，不充当 E2E 执行器（避免"自己测自己"的再入混淆）。

---

## 3. 验证路由分析（E2E 与控制对话框）

### 3.1 E2E（验证"执行"完整链路）
```
regime run <flow>  ──HTTP──▶  worker 容器(:4097)  真正干任务
        │
        └──▶ supervisor ──▶ Reporter（可观测）
```
- **已容器化驱动**：regime-driver（宿主）已通过 HTTP 驱动 worker，真实 E2E 此前多次 COMPLETE。
- **可选增强（你的思路）**：把 regime-driver 装进容器，实现"代码部署进容器、容器内自洽"。
- 目的：验证 worker 能完成一个真实工程任务（`[WORK_DONE]`→judge→advance→COMPLETE）。

### 3.2 控制对话框 A 路（验证"控制/监控"完整链路）
```
[程序化 HTTP 驱动]  ──建 dialog-control-agent session──▶  容器内 opencode(挂载 dialog-control.md+regime-dialog-control.js)
   status → run → monitor(sessions/events) → session send → report
```
- **关键洞察**：opencode 的 `serve`/`web` 暴露与 worker 相同的 session/message HTTP API
  （= regime-driver 驱动 worker 那套）。所以 A 路 dialog-control agent **可经 HTTP 程序化建会话并交互**，
  **完全绕开交互式 TUI**（即绕开"opencode run 挂起"）。
- 需要的容器配置：把 `dialog-control.md` + `regime-dialog-control.js` 挂载/复制进一个 opencode 实例，
  且该实例具备 regime-driver conda env（控制对话框工具 shell 出 `conda run -n regime-driver regime ...`）。
- 目的：验证 dialog-control agent 能经插件工具 + 权限门禁 + 手册真实控制/监控系统。

### 3.3 两条路由的分工（防混乱）
- **E2E** 只验证"执行能力"（worker 干得好不好）。
- **控制对话框 E2E** 验证"控制能力"（dialog-control 控制得对不对、看得到看不到全局）。
- 二者用同一套 HTTP 机制，但**目标对象不同**：E2E 目标是 worker 的任务执行，dialog-control E2E 目标是对话面的控制行为。

---

## 4. 防混乱规则（写成硬约束）

1. **开发 session 永不充当被测执行器**：本 session 只产代码/测试；E2E 一律在容器 worker 上跑。
2. **HTTP 是唯一验证驱动**：E2E / dialog-control 验证一律 HTTP 程序化；不依赖交互式 TUI。
3. **worker 只执行**：不装开发工具、不接人类，保持干净（防污染验证结果）。
4. **控制对话框会话必须在"有 dialog-control 配置 + 有 regime-driver env"的实例里跑**，否则工具/门禁不完整。
5. **每个容器只承担一个角色**：worker=执行、autopilot=web 窗/（可选）dialog-control 宿主；不混用。
6. **代码与运行分离**：regime-driver 代码在宿主开发；部署到容器用构建/同步，不在容器里写代码。

---

## 5. 任务分解（待实施，按序）

| # | 任务 | 状态 |
|---|---|---|
| T-A | **E2E 系统化**：把真实 worker HTTP 驱动整理成可回归的 E2E 测试 | ✅ `e2e_tests/test_e2e_worker.py`（REGIME_E2E 门控，真实 worker COMPLETE） |
| T-B | **对话面配置进容器**：建 `Dockerfile.dialog-control` + `docker/dialog-control-config/`，装 regime-driver + dialog-control.md + regime-dialog-control 插件，非 --pure，端口 4098 | ✅ `opencode-dialog-control` 容器运行（--network host） |
| T-C | **控制对话框 A 路 HTTP 驱动 E2E**：HTTP 建 控制对话框会话，dialog-control 调用插件工具真实控制 | ✅ 打通（regime_status 返回真实 worker 健康，dialog-control 结构化报告） |
| T-D | **regime-driver 容器化（可选，你的思路）** | ⏳ 可选；当前宿主驱动已够 |
| T-E | **文档/交接收口**：更新 HANDOVER/TECH_DEBT 标记 T1/T2/E2E 缺口已补 | 本文件 + HANDOVER |

> 注：T-C 打通过程暴露并修复 regime-dialog-control.js 三个真 bug（null-args 崩溃、conda run 输出丢失、
> `.text()` 不捕获）与 `validate --deep` 在无 skills-dir 时硬失败的过度默认。详见 tasks_docs/WORKLOG.md。

---

## 6. 关键设计决策

1. **控制对话框会话宿主用独立 控制对话框容器**：新建 `opencode-dialog-control` 容器（`docker/Dockerfile.dialog-control`，端口
   4098，`--network host`）承载控制对话框 A 路；worker 保持纯净执行（`serve --pure`，无插件）。
   采用 (b) 方案：worker 纯净、dialog-control 独立，角色不混用。
2. **E2E 不容器化 regime-driver**（原 T-D 可选）：保持宿主驱动真实 worker 容器即可，
   已验证足够；代码部署进容器不在当前范围。

---

## 7. 一句话

**职责不混乱的关键**：开发（本 session）≠ 执行（worker）≠ 控制（dialog-control）≠ 监督（supervisor）；
验证一律走 **HTTP 程序化驱动 + 容器里的干净实例**，绕开交互 TUI。E2E 验"执行"，dialog-control E2E 验"控制"，两路分工、同一机制。
