---
title: 故障排查
---

在阶段 0 中，请验证 Python 3.11+、Node 20+ 以及可编辑的开发安装。提供商、
沙箱、MCP 和工作流的故障排查将随相应真实功能的落地一并补充。

## 多智能体限制

`MultiAgentError` 会报告是哪个守卫拒绝了派生：活跃子级数、总子级数、深度、总令牌数或总耗时。在提高限制之前，请检查 `manager.list_agents()`、`manager.tokens_used` 和 `manager.event_history()`。被标记为 `budget_exhausted` 的子级已完成其请求但超出了其配额；后续的派生可能会被总预算阻止。

如果 `wait` 返回活跃的快照，说明其超时已到期；它不会取消子级。请使用更长的、事件驱动的等待，对单个子级使用 `interrupt_agent`，或对子树使用 `cancel(parent_id)`。不要使用极短的等待进行循环。

如果模型从不委派，请确认 `expose_tools=True` 并检查根 Thread 的工具定义。工具名称冲突会导致管理器构造失败，而不会静默替换应用工具。真正的 DeepSeek 委派还需要 `DEEPSEEK_API_KEY` 以及一个选择协作 Tools 的模型响应。

## 配置与延迟 Tools

运行 `super-harness --json doctor` 查看已解析的配置文件/来源名称。如果某个值出乎意料，
请按此优先级顺序依次检查运行时参数、`SUPER_HARNESS_*`、项目配置，再用户配置。
`.env` 除非应用选择启用，否则没有效果。失败的延迟加载器会保持延迟状态；
修复其依赖后再次调用 `load`。不匹配的限定名会被拒绝。

## 提供商回退

检查 `provider.attempt.*` 和 `provider.fallback.selected` 事件。除非配置的谓词显式允许，
否则身份认证错误不会切换。可见输出之后发生的流式失败会刻意拒绝回退；请改用带幂等策略的
方式重新启动更上层的操作，而不要拼接另一个提供商的响应。

## Docker 沙箱

`available()` 只检查 CLI。守护进程错误或缺失镜像会出现在 `stderr` 中；请在 Super Harness
之外安装或预拉取显式配置的镜像。运行时绝不会静默拉取。
挂载目标必须是绝对的容器路径，cwd 必须保持在工作区之内，且转发的
环境变量名必须经过允许名单。使用 `describe()` 和 `build_command()` 进行离线诊断。
