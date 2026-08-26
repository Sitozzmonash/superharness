"""Mask configured and common secret patterns before telemetry leaves the process."""

import json

from super_harness import SecretRedactor, SecretValue

redactor = SecretRedactor(secrets=["organization-private-value"])
safe = redactor.redact(
    {
        "api_key": "raw-key",
        "header": "Authorization: Bearer token-value",
        "custom": "organization-private-value",
        "wrapped": SecretValue("never-rendered"),
    }
)
print(json.dumps(safe, indent=2))
