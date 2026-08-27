---
title: 兼容性与测试
---

覆盖矩阵是一道发布门槛。仅 mock 的路径不算作真实的 provider E2E 证据，
任何特性只有在代码、测试、文档、示例和可观测性
都得到证据支持之后才能标记为完成。

阶段 6 的兼容性证据包括：从固定的 `openai/codex` GitHub 子目录安装的一个 Skill、用官方 MCP 2.x SDK 构建的一个真实 stdio/HTTP 服务器、一个隔离的官方 `mcp==1.29.1` 服务器协商一个具有代表性的 2025 协议，以及一次实时 Official MCP Registry 查询。设置 `SUPER_HARNESS_EXTERNAL_COMPAT=1` 以运行依赖网络/依赖项的检查；默认测试会显式跳过这些检查。

主要 HTTP 目标是 MCP `2026-07-28`。更早的 2025 协议处理被有意委托给官方 SDK，并保留在单独的兼容性测试中，这样旧行为就不会静默地重新定义当前的传输契约。

阶段 7 使用官方 `openai/plugins` 仓库的 `plugins/plugin-eval` 目录，提交哈希为 `11c74d6ba24d3a6d48f54a194cd00ef3beea18f9`。Codex JSON 导入器支持身份/版本/描述、Skill 根、MCP 路径或内联定义、被动 assets/agents/commands，并保留其他元数据。Codex apps/interface 保持被动；command/MCP 钩子文件会被报告，但绝不自动执行。

Super Harness TOML 叠加层添加了 Python Tool/钩子入口点和框架版本说明符。这是有意的扩展，因为插件格式不如 Agent Skills 或 MCP 那样标准化。

自主编排遵循锁定的 Codex 协作操作集和状态语义，但它是 Python API，而不是 Codex 协议的线级克隆。UUID 取代 Codex 任务路径；子级 `AgentFactory` 取代内部模型目录和执行器环境。全历史继承绝不静默改变 provider/模型策略，因为这些选择在工厂中保持显式。

真实的 DeepSeek 父/子工具链测试受凭证门槛限制。没有 `DEEPSEEK_API_KEY` 时，本地集成会用确定性 provider 证明完整的模型请求 Tool 循环，但矩阵保留 `Real E2E=TODO`。

锁定的 Codex 树不暴露通用的可执行 DAG 引擎；它的 `update_plan` 表面是一个类型化、发出事件的清单。Super Harness 有意用 provider 无关的 Python 工作流运行时扩展那些状态/事件原则。阶段 9 的 `Real E2E` 是 `N/A`：其产品边界是进程内调度器和本地原子 JSON 存储，两者都通过集成测试覆盖，无需 mock 或外部服务。

阶段 10 组合阶段 8 的 Agent 生命周期和阶段 9 的工作流运行时，而不定义新的线协议。自主节点使用与 F27 下测试的相同的模型可调用协作 Tools。混合 `Real E2E` 是 `N/A`，因为组合/取消/检查点是进程内控制边界；实时模型行为仍由 F27 的凭证门槛 E2E 状态准确代表。

阶段 11 遵循锁定的 Codex 对追踪安全元数据、更丰富的本地日志、经校验的指标、可选导出器和脱敏密钥的分离。它有意不克隆 Codex 的账户/会话字段、Statsig 默认值或 Rust 追踪目标。OTEL 网络/provider 设置仍归应用所有；框架边界通过注入的标准形状 tracer 测试，因此 F32 `Real E2E` 是 `N/A`。

安全加固总体上保持 `PARTIAL`：本地路径策略不是 Docker/VM 沙箱，显式启用的插件 Python 在进程内运行。这些限制是部署控制，而不是被静默呈现为强隔离。

阶段 12 遵循锁定的 Codex 对结构化诊断、显式生态系统
生命周期操作和持久恢复的分离。它有意使用 Python/SQLite/文件系统状态，
而非克隆 Codex 的应用服务器或市场协议。CLI 的 Real E2E 是 `N/A`，因为
CLI 边界是本地已安装的进程和文件系统，两者都由集成测试和
wheel 冒烟测试覆盖；外部 provider 和实时 Registry 证据仍然归属其各自的
特性行。

阶段 13 关闭了惰性 Tools、Router、Persona、配置/密钥和回退的本地缺口。
其规则/配置边界在进程内并使用 `Real E2E=N/A`；这并不豁免为它们可能选择的
provider 提供实时 provider 证据。Docker 不同：命令构造和
清理经过集成测试，但 `Real E2E` 保持 `TODO`，直到 Docker 守护进程和本地镜像
执行隔离测试。该测试绝不隐式下载镜像。

因此发布候选未被标记为 V1。当前外部阻碍是真实的 DeepSeek、
Zhipu 搜索和 Zhipu 视觉凭证；可选的网络兼容性执行；Docker
运行时/本地镜像；以及确认的 GitHub Pages 部署 URL。本地 PASS 证据不能
替代任何这些边界。

矩阵还将仅本地的行规范化为 `Real E2E=N/A`：Thread/Turn、上下文组装、
压缩、生命周期控制、事件迭代、working/SQLite 记忆、本地内置项/沙箱、
审批回调用、AGENTS 发现和 SQLite 持久化不暴露外部服务边界。
其实际的文件系统、进程、取消和数据库边界由集成测试覆盖；
依赖 provider 的行为只保留在相应的 provider/Agent 行上进行跟踪。