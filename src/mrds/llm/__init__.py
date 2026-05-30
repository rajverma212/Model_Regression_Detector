"""LLM client layer — isolates provider-specific code behind a small interface.

Features depend only on the :class:`StructuredLLMClient` protocol and the
provider-neutral :class:`LLMMessage` / :class:`LLMResult` types. The concrete
OpenAI implementation lives in :mod:`mrds.llm.openai_client` and is the only
module that imports the ``openai`` SDK.
"""

from mrds.llm.base import LLMMessage, LLMResult, StructuredLLMClient
from mrds.llm.errors import (
    LLMClientError,
    LLMConfigurationError,
    LLMError,
    LLMParseError,
)

__all__ = [
    "LLMClientError",
    "LLMConfigurationError",
    "LLMError",
    "LLMMessage",
    "LLMParseError",
    "LLMResult",
    "StructuredLLMClient",
]
