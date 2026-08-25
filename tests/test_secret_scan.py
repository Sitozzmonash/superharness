from __future__ import annotations

from pathlib import Path

from tools.check_secrets import find_likely_secrets


def test_secret_scan_detects_provider_key_and_openai_style_key(tmp_path: Path) -> None:
    provider_key = tmp_path / "provider.env"
    provider_key.write_text("DEEPSEEK_" + "API_KEY=" + "x", encoding="utf-8")
    openai_style = tmp_path / "other.txt"
    openai_style.write_text("sk-" + ("a" * 24), encoding="utf-8")

    findings = find_likely_secrets([provider_key, openai_style])

    assert [(finding[0], finding[1]) for finding in findings] == [
        (provider_key, 1),
        (openai_style, 1),
    ]


def test_secret_scan_ignores_empty_env_and_short_test_placeholder(tmp_path: Path) -> None:
    fixture = tmp_path / "safe.env"
    fixture.write_text("DEEPSEEK_" + "API_KEY=\napi_key=secret-value\n", encoding="utf-8")

    assert find_likely_secrets([fixture]) == []
