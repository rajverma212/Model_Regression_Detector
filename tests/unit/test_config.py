"""Tests for layered configuration."""

from __future__ import annotations

import pytest

from mrds.config.settings import Settings, get_settings


def test_defaults_are_sane(clear_secret_env: None) -> None:
    settings = Settings()
    assert settings.env == "local"
    assert settings.judge_enabled is False  # cost-aware default
    assert settings.anthropic_api_key is None
    assert settings.slack_webhook_url is None


def test_env_overrides_yaml(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MRDS_LOG_LEVEL", "DEBUG")
    assert get_settings().log_level == "DEBUG"


def test_secret_read_from_canonical_env_name(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-123")
    assert get_settings().anthropic_api_key == "sk-ant-test-123"
