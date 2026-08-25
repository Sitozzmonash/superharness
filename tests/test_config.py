from __future__ import annotations

import pytest
from pydantic import ValidationError

from super_harness.config import HarnessConfig, ProfileName, SecretValue, redact_text


def test_china_profile_is_the_provider_independent_default_shape() -> None:
    config = HarnessConfig()

    assert config.profile is ProfileName.CHINA
    assert config.model.provider == "deepseek"
    assert config.model.model == "deepseek-v4-flash"
    assert config.approval.mode == "full_access"
    assert config.sandbox.mode == "workspace_write"


def test_config_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        HarnessConfig(unknown=True)  # type: ignore[call-arg]


def test_secret_value_masks_string_and_repr() -> None:
    secret = SecretValue("live-secret")

    assert str(secret) == "********"
    assert "live-secret" not in repr(secret)
    assert secret.reveal() == "live-secret"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Authorization: Bearer abc.def", "Authorization: Bearer ********"),
        ("api_key=secret-value", "api_key=********"),
        ("token: xyz", "token: ********"),
    ],
)
def test_redact_text_masks_common_secret_patterns(text: str, expected: str) -> None:
    assert redact_text(text) == expected
