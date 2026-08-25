from super_harness import PluginInstaller, PluginManager

manager = PluginManager(PluginInstaller(".super-harness/plugins"))
for installed in manager.list():
    print(installed.manifest.name, installed.enabled, installed.source)
manager.update("release-tools")  # disabled plugins only
manager.remove("release-tools")
