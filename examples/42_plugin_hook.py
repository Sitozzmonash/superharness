from super_harness import HookRegistry, PluginInstaller, PluginManager

hooks = HookRegistry()
manager = PluginManager(PluginInstaller(".super-harness/plugins"), hooks=hooks)
capabilities = manager.enable("release-tools")
print("registered plugin hooks:", capabilities.hooks)
