---
title: 生态系统
---

Super Harness 将在定义项目特有的格式之前，先消费现有的 Agent Skills、Model Context Protocol、Python 入口点以及兼容 Codex 的插件约定。

## Agent Skills

阶段 6 消费标准的 `SKILL.md` 前置元数据与目录资源。支持本地与 HTTPS Git/GitHub 安装，包括位于分支、标签或提交上的仓库子目录。安装出处信息存储在 `.super-harness-source.json` 中。

## Model Context Protocol

stdio 与 Streamable HTTP 均使用官方 Python SDK。可以导入通用的 `mcpServers` JSON。远程工具通过常规的 Super Harness 工具抽象暴露，而资源与提示词则继续通过显式的 MCP 客户端方法获取。

## MCPB 与注册表

`.mcpb` 归档会经过完整性检查与归档安全检查后才会被检查并安装。官方 MCP 注册表预览端点可通过可替换的适配器使用；注册表发现并不意味着信任或自动安装。

## 插件与钩子

Super Harness 插件使用 `.super-harness/plugin.toml`；`.codex-plugin/plugin.json` 会以尽力而为的方式导入。每个相对能力路径都必须以 `./` 开头并保持在插件根目录之内。支持本地与固定版本的 HTTPS Git/GitHub 源，并带有源元数据与显式启用机制。

Python 工具包也可能在未来的版本中暴露常规入口点，但阶段 7 不会自动发现或执行已安装的包入口点。插件 Python 只会为显式启用的清单条目导入。

## CLI 安装流程

阶段 12 通过 `super-harness skill`、`super-harness mcp` 与
`super-harness plugin` 暴露经过验证的安装器。默认范围为本地项目，`--global` 则选择用户范围。
MCP 支持直接的 stdio/HTTP 定义、通用 JSON 导入、经过完整性检查的 MCPB 包，
以及可选的官方注册表搜索/安装元数据。注册表发现并不意味着信任。
插件管理仅涉及数据；激活仍然是显式的 Python API 信任边界。