"""Anthropic implementation of :class:`StructuredLLMClient`.

This is the *only* module that imports the ``anthropic`` SDK. It uses the
Messages API structured-output helper (``client.messages.parse``) with a Pydantic
``output_format`` to obtain natively validated structured outputs — not a
free-text completion that is parsed after the fact.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, TypeVar

from anthropic import Anthropic, AnthropicError
from pydantic import BaseModel

from mrds.llm.base import LLMMessage, LLMResult
from mrds.llm.errors import LLMClientError, LLMParseError
from mrds.observability.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)

# Structured classification/extraction outputs are small; this ceiling only guards
# against a runaway generation and sits comfortably above any feature's schema.
DEFAULT_MAX_TOKENS = 4096


class AnthropicStructuredClient:
    """Structured-output client backed by the Anthropic Messages API.

    Satisfies the :class:`~mrds.llm.base.StructuredLLMClient` protocol structurally.
    An ``Anthropic`` instance may be injected (useful for tests); otherwise one is
    constructed from the supplied API key.
    """

    def __init__(
        self,
        *,
        api_key: str,
        client: Anthropic | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self._client = client or Anthropic(api_key=api_key)
        self._max_tokens = max_tokens

    def parse_structured(
        self,
        *,
        model: str,
        messages: Sequence[LLMMessage],
        schema: type[T],
    ) -> LLMResult[T]:
        """Send ``messages`` and parse the structured response into ``schema``.

        The Anthropic Messages API has no ``system``/``developer`` chat roles, so
        those turns are folded into the top-level ``system`` prompt; only
        ``user``/``assistant`` turns are sent in ``messages``.
        """
        system = "\n\n".join(m.content for m in messages if m.role in ("system", "developer"))
        chat = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role in ("user", "assistant")
        ]

        request: dict[str, Any] = {
            "model": model,
            "max_tokens": self._max_tokens,
            "messages": chat,
            "output_format": schema,
        }
        if system:
            request["system"] = system

        try:
            response = self._client.messages.parse(**request)
        except AnthropicError as exc:
            raise LLMClientError(f"Anthropic request failed: {exc}") from exc

        parsed = response.parsed_output
        if parsed is None:
            raise LLMParseError("Model returned no parseable structured output (possible refusal).")

        usage = response.usage
        input_tokens = getattr(usage, "input_tokens", 0) or 0
        output_tokens = getattr(usage, "output_tokens", 0) or 0
        return LLMResult(
            parsed=parsed,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        )
