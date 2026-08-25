from super_harness import HookRegistry, PluginInstaller, PluginManager, ToolRegistry

tools = ToolRegistry()
hooks = HookRegistry()
manager = PluginManager(
    PluginInstaller(".super-harness/plugins"), tools=tools, hooks=hooks
)
capabilities = manager.enable("release-tools")
print(capabilities.skills, capabilities.tools, capabilities.mcp_servers, capabilities.hooks)
