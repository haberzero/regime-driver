# 快速开始：用对话跑通第一个任务

> 本篇让你**最快**用上 regime-driver。前提是你已经装好环境（见 [安装](03_environment.md)）。
> 重点不是学命令，而是感受"和对话框对话"就能完成任务。

## 1. 打开上帝对话框

```bash
conda run -n regime-driver regime dialog --live --perm run
```

看到 `God>` 提示符，就进入了上帝对话框。
`--live` 表示连接真实 worker，`--perm run` 允许启动任务。

## 2. 先问一句"现在什么状态"

在 `God>` 后输入：

```text
God> status
```

它会告诉你 worker 是否健康、有没有正在运行的任务。用自然语言提问也可以，例如：
"现在系统状态怎么样？"（`--live` 时会用模型解释）。

## 3. 用一句话启动一个任务

```text
God> start code_workflow 实现一个函数 f(x)=x*2 并写测试
```

对话框非阻塞启动这个任务，给你一个编号。你可以继续问别的，不用干等。

## 4. 看任务跑到哪了

```text
God> watch
```

查看最近事件，观察任务推进。

## 5. 等它完成

任务完成后，对话框会汇报结果。你也可以随时 `status` 查看。

## 完成！

你已经用对话完成了第一个 regime-driver 任务——没有写任何 JSON、没有记一堆参数。

接下来，看看 [你能做什么](02_capabilities.md) 了解全部能力；
或者 [安装环境](03_environment.md) 如果你想从零搭建。

## 深入指引

- 想了解上帝对话框为什么存在、怎么设计：`00_god_dialog.md`
- 全部能力清单：`02_capabilities.md`
- 对话框命令细节（查询用）：`../reference/05_god_dialog_contract.md`
