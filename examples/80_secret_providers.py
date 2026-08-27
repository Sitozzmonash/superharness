"""Resolve secrets explicitly while keeping diagnostics masked."""

from super_harness import CompositeSecretProvider, EnvironmentSecretProvider, MappingSecretProvider

secrets = CompositeSecretProvider(
    (EnvironmentSecretProvider({}), MappingSecretProvider({"SERVICE_TOKEN": "demo-secret"}))
)
token = secrets.get("SERVICE_TOKEN")
print(token, token.reveal() == "demo-secret" if token else False)

