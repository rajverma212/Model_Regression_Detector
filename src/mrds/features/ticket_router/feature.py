"""The support-ticket-routing feature.

A second feature under test, onboarded to validate that MRDS is feature-agnostic.
It follows exactly the same :class:`~mrds.core.interfaces.Feature` contract as the
email classifier:

- declares its input/output Pydantic models,
- loads its prompt through the prompt registry (no hardcoded prompts),
- builds a chat request (system prompt + few-shot examples + the ticket),
- calls the LLM via the injected :class:`StructuredLLMClient`, and
- returns a validated :class:`TicketRoutingOutput`.

It is registered into the global feature registry like any other feature.
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel

from mrds.config.settings import Settings, get_settings
from mrds.core.errors import FeatureExecutionError
from mrds.core.interfaces import Feature, FeatureRunResult, Scorer
from mrds.features.ticket_router.schema import (
    TicketRoutingInput,
    TicketRoutingOutput,
)
from mrds.features.ticket_router.scorers import (
    CategoryMatchScorer,
    PriorityMatchScorer,
)
from mrds.llm.base import LLMMessage, LLMResult, StructuredLLMClient
from mrds.llm.errors import LLMConfigurationError, LLMError
from mrds.observability.logging import get_logger
from mrds.prompts.loader import DEFAULT_PROMPTS_DIR
from mrds.prompts.models import LoadedPrompt
from mrds.prompts.registry import PromptRegistry

logger = get_logger(__name__)


class TicketRouterFeature(Feature):
    """Support ticket routing — the platform's second feature."""

    name: ClassVar[str] = "ticket_router"
    dataset_ref: ClassVar[str] = "ticket_router"

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
        return TicketRoutingInput

    @property
    def output_model(self) -> type[BaseModel]:
        return TicketRoutingOutput

    def scorers(self) -> list[Scorer]:
        return [CategoryMatchScorer(), PriorityMatchScorer()]

    def run(self, payload: BaseModel | Mapping[str, Any]) -> TicketRoutingOutput:
        """Route a single ticket into a validated :class:`TicketRoutingOutput`."""
        return self._route(payload).parsed

    def run_with_usage(self, payload: BaseModel | Mapping[str, Any]) -> FeatureRunResult:
        """Route a single ticket and report token usage."""
        result = self._route(payload)
        return FeatureRunResult(
            output=result.parsed,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            total_tokens=result.total_tokens,
        )

    def _route(self, payload: BaseModel | Mapping[str, Any]) -> LLMResult[TicketRoutingOutput]:
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
                schema=TicketRoutingOutput,
            )
        except LLMError as exc:
            logger.error("ticket_router LLM call failed: %s", exc)
            raise FeatureExecutionError(f"ticket_router failed: {exc}") from exc

        logger.info(
            "ticket_router routed ticket as '%s'/'%s' (prompt=%s, tokens=%d)",
            result.parsed.category.value,
            result.parsed.priority.value,
            prompt.identity,
            result.total_tokens,
        )
        return result

    # -- helpers ----------------------------------------------------------------

    @staticmethod
    def _coerce_input(payload: BaseModel | Mapping[str, Any]) -> TicketRoutingInput:
        if isinstance(payload, TicketRoutingInput):
            return payload
        if isinstance(payload, Mapping):
            return TicketRoutingInput.model_validate(payload)
        raise FeatureExecutionError(
            f"unsupported input type for ticket_router: {type(payload).__name__}"
        )

    def _build_messages(self, prompt: LoadedPrompt, data: TicketRoutingInput) -> list[LLMMessage]:
        messages: list[LLMMessage] = [
            LLMMessage(role="system", content=prompt.definition.system_prompt)
        ]
        for example in prompt.definition.few_shot_examples:
            messages.append(LLMMessage(role="user", content=example.input))
            messages.append(LLMMessage(role="assistant", content=example.output))
        messages.append(LLMMessage(role="user", content=data.ticket_text))
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
        if not settings.openai_api_key:
            raise LLMConfigurationError(
                "OPENAI_API_KEY is not set; cannot run ticket_router against OpenAI."
            )
        # Imported lazily so the openai SDK is only required at real run time.
        from mrds.llm.openai_client import OpenAIStructuredClient

        self._client = OpenAIStructuredClient(api_key=settings.openai_api_key)
        return self._client


def build_feature() -> TicketRouterFeature:
    """Factory used during registration (see :mod:`mrds.features`)."""
    return TicketRouterFeature()
