"""Shared pytest fixtures for the MRDS test suite."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _isolate_dotenv(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the suite hermetic by ignoring a developer's local ``.env``.

    The app intentionally loads ``.env`` in production; tests, however, must be
    deterministic regardless of whether one exists, so we disable it here only.
    """
    from mrds.config.settings import Settings

    monkeypatch.setitem(Settings.model_config, "env_file", None)


@pytest.fixture
def clear_secret_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove secret env vars so default-value tests are hermetic.

    CI environments may export ``ANTHROPIC_API_KEY`` / ``SLACK_WEBHOOK_URL``; tests
    asserting default behaviour should not depend on the host environment.
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
