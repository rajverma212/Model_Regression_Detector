"""Error hierarchy for the LLM client layer (provider-neutral)."""

from __future__ import annotations


class LLMError(Exception):
    """Base class for all LLM client errors."""


class LLMConfigurationError(LLMError):
    """Raised when the client is misconfigured (e.g. missing API key)."""


class LLMClientError(LLMError):
    """Raised when the underlying provider request fails."""


class LLMParseError(LLMError):
    """Raised when the provider returns no parseable structured output."""
