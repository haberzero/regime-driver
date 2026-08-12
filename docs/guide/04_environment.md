# 安装运行环境

本文带你安装 regime-driver 的运行环境。
面向第一次接触本仓库的新用户。
覆盖 conda 环境、可编辑安装与验证。

## 你将会学到

- 用 conda 创建隔离的 Python 环境。
- 安装 regime-driver（源码方式 / wheel 方式）。
- 验证环境安装正确。

## 两种安装方式

| 方式 | 场景 | 命令 |
|---|---|---|
| **从源码（可编辑）** | 你要开发/修改 regime-driver 本身 | `pip install -e ".[dev]"`（在本仓库根目录） |
| **从 wheel（发布后）** | 你只是用它跑任务 | `pip install regime-driver` |

> 本仓库目前仍在开发中、未发布到 PyPI，所以当前实际上用源码方式安装。
> wheel 方式在发布后可用；两种方式都自带官方模板（`regime scaffold` 一键部署）。

## 前置要求

- 已安装 conda 或 miniconda。
- 已安装 Docker（方式 A 容器化运行需要，见《配置模型与密钥》）。
- 已能访问命令行的本仓库副本。

## 步骤

### 1. 创建 conda 环境

regime-driver 需要 Python 3.11 或更高。
创建一个名为 `regime-driver` 的环境。

```bash
conda create -n regime-driver python=3.12
```

预期结果：conda 创建新环境并提示激活方式。
后续命令都用 `conda run -n regime-driver` 执行，无需手动激活。

### 2. 可编辑安装项目

在仓库根目录执行可编辑安装。
`-e` 使源码改动即时生效，免重复安装。

```bash
conda run -n regime-driver pip install -e ".[dev]"
```

预期结果：pip 安装项目并生成 `regime` 命令入口。
安装结束后无报错即为成功。

### 3. 理解依赖分组

项目用 `pyproject.toml` 声明依赖。
运行时依赖放在 `[project.dependencies]`。
dev 依赖放在 `[project.optional-dependencies]` 的 `dev` 分组。

dev 分组包含 pytest 与 pytest-cov。
它们只用于开发与测试，不进入生产运行时。
`".[dev]"` 语法表示：安装本项目且附带 dev 分组。

### 4. 验证安装

检查 `regime` 命令可用，并列出其子命令。

```bash
conda run -n regime-driver regime --help
```

预期结果：打印 `regime` 的帮助与全部子命令。
出现 `regime = "regime_driver.cli:app"` 对应入口即安装正确。

### 5. 验证测试可运行

跑一次测试套件确认环境完整。

```bash
conda run -n regime-driver python -m pytest -q
```

预期结果：测试全部通过并显示通过数量。
若本机未配置模型密钥，真实 worker 相关测试可能跳过。
具体通过数以 `python -m pytest` 实跑为准。

## 你现在能做什么

- 已有一个可用的 regime-driver 开发环境。
- 能执行任意 `regime` 子命令。
- 能运行测试套件验证改动。

下一步进入《配置模型与密钥》。

## 深入指引

- 依赖声明与 dev 分组：`pyproject.toml`
- 环境变量覆盖与优先级：`config.example.toml`
- 全部命令契约：`../CLI_REFERENCE.md`
