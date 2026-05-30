"""Error hierarchy for the prompt-management subsystem."""

from __future__ import annotations


class PromptError(Exception):
    """Base class for all prompt-management errors."""


class PromptValidationError(PromptError):
    """Raised when a prompt file is malformed or fails schema validation."""


class PromptNotFoundError(PromptError):
    """Raised when a requested feature/version is not in the registry."""
