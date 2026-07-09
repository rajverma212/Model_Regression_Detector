"""Layered application configuration for MRDS.

Configuration precedence (low to high):

1. Built-in defaults (declared on this model)
2. ``config/settings.yaml`` (committed, non-secret)
3. Environment variables / ``.env`` (secrets and per-environment overrides)

Secrets (``ANTHROPIC_API_KEY``, ``SLACK_WEBHOOK_URL``) are read from their canonical
environment-variable names and are never committed. All other settings use the
``MRDS_`` environment prefix (e.g. ``MRDS_LOG_LEVEL``).

No client, database, or feature logic lives here — this module only resolves and
validates configuration values.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic import Field
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    YamlConfigSettingsSource,
)

DEFAULT_CONFIG_FILE = Path("config/settings.yaml")


class Settings(BaseSettings):
    """Validated, layered configuration for the platform.

    Values are resolved from defaults, then the YAML config file, then the
    environment (env vars take precedence over YAML).
    """

    model_config = SettingsConfigDict(
        env_prefix="MRDS_",
        env_file=".env",
        env_file_encoding="utf-8",
        yaml_file=DEFAULT_CONFIG_FILE,
        extra="ignore",
    )

    # --- Environment / runtime -------------------------------------------------
    env: Literal["local", "ci"] = "local"
    log_level: str = "INFO"
    json_logs: bool = False

    # --- Persistence ----------------------------------------------------------
    # Which storage backend serves as EvalOS's system of record. Selected here and
    # built by ``mrds.db.create_backend``; the rest of the system depends only on
    # the backend interface, so changing engines is configuration, not code.
    storage_backend: Literal["sqlite"] = "sqlite"
    # Local SQLite database file (used by the ``sqlite`` backend).
    database_path: Path = Path("data/eval.db")

    # --- Model defaults --------------------------------------------------------
    model: str = "claude-haiku-4-5"
    judge_enabled: bool = False

    # --- Demo mode -------------------------------------------------------------
    # When true, the dashboard seeds deterministic offline demo data into an empty
    # database so visitors see meaningful pages without Anthropic API access.
    # Bound to MRDS_DEMO (not the prefix-derived MRDS_DEMO_MODE) to match the docs.
    demo_mode: bool = Field(default=False, validation_alias="MRDS_DEMO")

    # --- Secrets (canonical env names, no MRDS_ prefix) ------------------------
    anthropic_api_key: str | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    slack_webhook_url: str | None = Field(default=None, validation_alias="SLACK_WEBHOOK_URL")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Add the YAML source as the lowest-priority source.

        Order is highest-to-lowest priority, so env/dotenv override the YAML file.
        """
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            file_secret_settings,
            YamlConfigSettingsSource(settings_cls),
        )


def get_settings() -> Settings:
    """Build and return a freshly resolved :class:`Settings` instance."""
    return Settings()
