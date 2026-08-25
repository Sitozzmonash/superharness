from super_harness import PluginInstaller

installer = PluginInstaller(".super-harness/plugins")
installed = installer.install("./plugins/release-tools")
print(installed.manifest.name, installed.manifest.version, installed.source)
