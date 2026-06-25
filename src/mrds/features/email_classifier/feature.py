"""The email-classification feature implementation.

This feature:

- declares its input/output Pydantic models,
- loads its prompt through the Sprint 2 prompt registry (no hardcoded prompts),
- builds a chat request (system prompt + few-shot examples + the email),
- calls the LLM via the injected :class:`StructuredLLMClient` (modern structured
  outputs only), and
- returns a validated :class:`EmailClassificationOutput`.

It is registered into the global feature registry exactly like any future feature.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel

from mrds.config.settings import Settings, get_settings
from mrds.core.errors import FeatureExecutionError
from mrds.core.interfaces import Feature, FeatureRunResult, Scorer
from mrds.features.email_classifier.schema import (
    EmailClassificationInput,
    EmailClassificationOutput,
)
from mrds.features.email_classifier.scorers import (
    CategoryMatchScorer,
    SummaryQualityScorer,
)
from mrds.llm.base import LLMMessage, LLMResult, StructuredLLMClient
from mrds.llm.errors import LLMConfigurationError, LLMError
from mrds.observability.logging import get_logger
from mrds.prompts.loader import DEFAULT_PROMPTS_DIR
from mrds.prompts.models import LoadedPrompt
from mrds.prompts.registry import PromptRegistry

logger = get_logger(__name__)


class EmailClassifierFeature(Feature):
    """Customer support email classification — the platform's first feature."""

    name: ClassVar[str] = "email_classifier"
    dataset_ref: ClassVar[str] = "email_classifier"

    def __init__(
        self,
        *,
        client: StructuredLLMClient | None = None,
        prompt_registry: PromptRegistry | None = None,
        prompt_version: str | None = None,
        settings: Settings | None = None,
        prompts_dir: Path = DEFAULT_PROMPTS_DIR,
    ) -> None:
        # Everything is lazy so that *registration* never needs secrets, a network,
        # or filesystem access — only an actual ``run`` does.
        self._client = client
        self._prompt_registry = prompt_registry
        self._prompt_version = prompt_version
        self._settings = settings
        self._prompts_dir = prompts_dir
        self._cached_prompt: LoadedPrompt | None = None

    # -- Feature contract -------------------------------------------------------

    @property
    def input_model(self) -> type[BaseModel]:
        return EmailClassificationInput

    @property
    def output_model(self) -> type[BaseModel]:
        return EmailClassificationOutput

    def scorers(self) -> list[Scorer]:
        return [CategoryMatchScorer(), SummaryQualityScorer()]

    def run(self, payload: BaseModel | Mapping[str, Any]) -> EmailClassificationOutput:
        """Classify a single email into a validated :class:`EmailClassificationOutput`."""
        return self._classify(payload).parsed

    def run_with_usage(self, payload: BaseModel | Mapping[str, Any]) -> FeatureRunResult:
        """Classify a single email and report token usage."""
        result = self._classify(payload)
        return FeatureRunResult(
            output=result.parsed,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            total_tokens=result.total_tokens,
        )

    def _classify(
        self, payload: BaseModel | Mapping[str, Any]
    ) -> LLMResult[EmailClassificationOutput]:
        """Resolve prompt/client, call the model, and return the full LLM result."""
        data = self._coerce_input(payload)
        prompt = self._resolve_prompt()
        messages = self._build_messages(prompt, data)
        client = self._get_client()
        model = self._resolve_settings().model

        try:
            result = client.parse_structured(
                model=model,
                messages=messages,
                schema=EmailClassificationOutput,
            )
        except LLMError as exc:
            logger.error("email_classifier LLM call failed: %s", exc)
            raise FeatureExecutionError(f"email_classifier failed: {exc}") from exc

        logger.info(
            "email_classifier classified email as '%s' (prompt=%s, tokens=%d)",
            result.parsed.category.value,
            prompt.identity,
            result.total_tokens,
        )
        return result

    # -- helpers ----------------------------------------------------------------

    @staticmethod
    def _coerce_input(payload: BaseModel | Mapping[str, Any]) -> EmailClassificationInput:
        if isinstance(payload, EmailClassificationInput):
            return payload
        if isinstance(payload, Mapping):
            return EmailClassificationInput.model_validate(payload)
        raise FeatureExecutionError(
            f"unsupported input type for email_classifier: {type(payload).__name__}"
        )

    def _build_messages(
        self, prompt: LoadedPrompt, data: EmailClassificationInput
    ) -> list[LLMMessage]:
        messages: list[LLMMessage] = [
            LLMMessage(role="system", content=prompt.definition.system_prompt)
        ]
        for example in prompt.definition.few_shot_examples:
            messages.append(LLMMessage(role="user", content=example.input))
            messages.append(LLMMessage(role="assistant", content=example.output))
        messages.append(LLMMessage(role="user", content=data.email_text))
        return messages

    def _resolve_prompt(self) -> LoadedPrompt:
        if self._cached_prompt is not None:
            return self._cached_prompt
        registry = self._prompt_registry or PromptRegistry.from_directory(self._prompts_dir)
        prompt = (
            registry.get(self.name, self._prompt_version)
            if self._prompt_version
            else registry.get_latest(self.name)
        )
        self._cached_prompt = prompt
        return prompt

    def _resolve_settings(self) -> Settings:
        return self._settings or get_settings()

    def _get_client(self) -> StructuredLLMClient:
        if self._client is not None:
            return self._client
        settings = self._resolve_settings()
        if not settings.anthropic_api_key:
            raise LLMConfigurationError(
                "ANTHROPIC_API_KEY is not set; cannot run email_classifier against Anthropic."
            )
        # Imported lazily so the anthropic SDK is only required at real run time.
        from mrds.llm.anthropic_client import AnthropicStructuredClient

        self._client = AnthropicStructuredClient(api_key=settings.anthropic_api_key)
        return self._client


def build_feature() -> EmailClassifierFeature:
    """Factory used during registration (see :mod:`mrds.features`)."""
    return EmailClassifierFeature()
