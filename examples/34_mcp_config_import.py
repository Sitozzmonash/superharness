from super_harness import import_mcp_servers

configs = import_mcp_servers("mcp.json")
for config in configs:
    print(config.name, config.transport)
