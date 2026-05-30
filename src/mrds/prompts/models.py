"""Pydantic v2 models for versioned prompt artifacts.

A prompt file declares behaviour-defining content (the system prompt and few-shot
examples) plus provenance metadata (version, creation date, description, tags).
Unknown keys are rejected so malformed files fail loudly.
"""

from __future__ import annotations

import re
from datetime import date
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, field_validator

VERSION_PATTERN = re.compile(r"^v\d+$")


class FewShotExample(BaseModel):
    """A single in-context example: an input and its expected output."""

    model_config = ConfigDict(extra="forbid")

    input: str = Field(min_length=1, description="Example input shown to the model.")
    output: str = Field(min_length=1, description="Expected output for the example.")

    @field_validator("input", "output")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


class PromptDefinition(BaseModel):
    """A single versioned prompt definition, as parsed from a YAML file.

    Identity for humans is ``(feature, version)``; identity for change-detection
    is the content hash (see :func:`mrds.prompts.loader.compute_content_hash`),
    which intentionally excludes the provenance-only ``created_at`` field.
    """

    model_config = ConfigDict(extra="forbid")

    version: str = Field(description="Version label, e.g. 'v1'.")
    created_at: date = Field(description="Authoring date (provenance only).")
    description: str = Field(min_length=1, description="Human summary of this version.")
    system_prompt: str = Field(min_length=1, description="The system prompt text.")
    few_shot_examples: list[FewShotExample] = Field(
        default_factory=list, description="Optional in-context examples."
    )
    tags: list[str] = Field(default_factory=list, description="Free-form classification tags.")

    @field_validator("version")
    @classmethod
    def _valid_version(cls, value: str) -> str:
        if not VERSION_PATTERN.match(value):
            raise ValueError("version must match 'v<number>' (e.g. 'v1', 'v2')")
        return value

    @field_validator("description", "system_prompt")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value

    @field_validator("tags")
    @classmethod
    def _tags_not_blank(cls, value: list[str]) -> list[str]:
        if any(not tag.strip() for tag in value):
            raise ValueError("tags must not be blank")
        return value

    @property
    def version_number(self) -> int:
        """Numeric component of the version label (``v3`` -> ``3``)."""
        return int(self.version[1:])


class LoadedPrompt(BaseModel):
    """A validated prompt definition plus its resolved identity and provenance."""

    model_config = ConfigDict(frozen=True)

    feature: str = Field(description="Feature the prompt belongs to (from its directory).")
    definition: PromptDefinition
    content_hash: str = Field(description="Deterministic, content-based hash.")
    source_path: Path = Field(description="File the prompt was loaded from.")

    @property
    def version(self) -> str:
        """Convenience accessor for the prompt version label."""
        return self.definition.version

    @property
    def identity(self) -> str:
        """Human-readable identity, e.g. ``email_classifier:v1``."""
        return f"{self.feature}:{self.version}"
