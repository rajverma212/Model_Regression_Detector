"""Prompt management: prompts as first-class, versioned, content-hashed artifacts.

Responsibilities are split across modules:

- :mod:`mrds.prompts.models` — Pydantic domain/metadata models.
- :mod:`mrds.prompts.validation` — turn raw data into a validated definition.
- :mod:`mrds.prompts.loader` — file I/O, YAML parsing, content hashing.
- :mod:`mrds.prompts.registry` — filesystem discovery and version resolution.
- :mod:`mrds.prompts.errors` — the prompt error hierarchy.
"""

from mrds.prompts.errors import (
    PromptError,
    PromptNotFoundError,
    PromptValidationError,
)
from mrds.prompts.loader import (
    DEFAULT_PROMPTS_DIR,
    compute_content_hash,
    load_prompt_file,
)
from mrds.prompts.models import FewShotExample, LoadedPrompt, PromptDefinition
from mrds.prompts.registry import PromptRegistry

__all__ = [
    "DEFAULT_PROMPTS_DIR",
    "FewShotExample",
    "LoadedPrompt",
    "PromptDefinition",
    "PromptError",
    "PromptNotFoundError",
    "PromptRegistry",
    "PromptValidationError",
    "compute_content_hash",
    "load_prompt_file",
]
