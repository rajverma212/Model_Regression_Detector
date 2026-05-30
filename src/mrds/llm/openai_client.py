"""OpenAI implementation of :class:`StructuredLLMClient`.

This is the *only* module that imports the ``openai`` SDK. It uses the modern
**Responses API** (``client.responses.parse``) with a Pydantic ``text_format`` to
obtain native structured outputs — not the legacy ``chat.completions.create``
free-text pattern.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypeVar

from openai import OpenAI, OpenAIError
from pydantic import BaseModel

from mrds.llm.base import LLMMessage, LLMResult
from mrds.llm.errors import LLMClientError, LLMParseError
from mrds.observability.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T", bound=BaseModel)


class OpenAIStructuredClient:
    """Structured-output client backed by the OpenAI Responses API.

    Satisfies the :class:`~mrds.llm.base.StructuredLLMClient` protocol structurally.
    An ``OpenAI`` instance may be injected (useful for tests); otherwise one is
    constructed from the supplied API key.
    """

    def __init__(self, *, api_key: str, client: OpenAI | None = None) -> None:
        self._client = client or OpenAI(api_key=api_key)

    def parse_structured(
        self,
        *,
        model: str,
        messages: Sequence[LLMMessage],
        schema: type[T],
    ) -> LLMResult[T]:
        """Send ``messages`` and parse the structured response into ``schema``."""
        request_input = [{"role": m.role, "content": m.content} for m in messages]

        try:
            response = self._client.responses.parse(
                model=model,
                input=request_input,
                text_format=schema,
            )
        except OpenAIError as exc:
            raise LLMClientError(f"OpenAI request failed: {exc}") from exc

        parsed = response.output_parsed
        if parsed is None:
            raise LLMParseError("Model returned no parseable structured output (possible refusal).")

        usage = response.usage
        return LLMResult(
            parsed=parsed,
            model=model,
            input_tokens=getattr(usage, "input_tokens", 0) or 0,
            output_tokens=getattr(usage, "output_tokens", 0) or 0,
            total_tokens=getattr(usage, "total_tokens", 0) or 0,
        )
