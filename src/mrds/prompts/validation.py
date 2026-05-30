"""Validation of raw prompt data into a typed :class:`PromptDefinition`.

This module is the single place that turns an untrusted mapping (parsed from
YAML) into a validated definition, translating Pydantic errors into the
subsystem's :class:`PromptValidationError`. Keeping it separate from the loader
isolates *schema* concerns from *file I/O* concerns.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import ValidationError

from mrds.prompts.errors import PromptValidationError
from mrds.prompts.models import PromptDefinition


def validate_prompt_data(data: Any, *, source: Path | None = None) -> PromptDefinition:
    """Validate parsed prompt data, returning a :class:`PromptDefinition`.

    Args:
        data: The object parsed from a prompt file (expected: a mapping).
        source: Optional source path, used to produce clearer error messages.

    Raises:
        PromptValidationError: If the data is not a mapping or fails validation.
    """
    where = f" in {source}" if source is not None else ""

    if not isinstance(data, dict):
        raise PromptValidationError(
            f"Prompt content{where} must be a mapping, got {type(data).__name__}."
        )

    try:
        return PromptDefinition.model_validate(data)
    except ValidationError as exc:
        raise PromptValidationError(f"Invalid prompt{where}:\n{exc}") from exc
