from super_harness import install_mcpb

bundle = install_mcpb("server.mcpb", ".super-harness/mcp", expected_sha256="EXPECTED_SHA256")
print(bundle.name, bundle.config.command, bundle.config.args)
