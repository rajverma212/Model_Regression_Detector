"""A single generic Feature implementation, parameterized by a :class:`FeatureSpec`.

`GenericStructuredFeature` satisfies the exact :class:`~mrds.core.interfaces.Feature`
contract the platform already consumes — generated input/output models, library
scorers, and the same prompt → LLM → parse run path as the hand-coded features. The
evaluation engine, dataset resolver, metrics, regression detector, DB, and dashboard
therefore use it with no changes.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, ClassVar

from pydantic import BaseModel

from mrds.config.settings import Settings, get_settings
from mrds.core.errors import FeatureExecutionError
from mrds.core.interfaces import Feature, FeatureRunResult, Scorer
from mrds.features.spec.models import build_input_model, build_output_model
from mrds.features.spec.scorers import build_scorer
from mrds.features.spec.spec import FeatureSpec
from mrds.llm.base import LLMMessage, LLMResult, StructuredLLMClient
from mrds.llm.errors import LLMConfigurationError, LLMError
from mrds.observability.logging import get_logger
from mrds.prompts.loader import DEFAULT_PROMPTS_DIR
from mrds.prompts.models import LoadedPrompt
from mrds.prompts.registry import PromptRegistry

logger = get_logger(__name__)


class GenericStructuredFeature(Feature):
    """A spec-driven structured-output feature (no per-feature Python)."""

    # Declared as ClassVar on the base; set per-instance here from the spec.
    name: ClassVar[str]
    dataset_ref: ClassVar[str]

    def __init__(
        self,
        spec: FeatureSpec,
        *,
        client: StructuredLLMClient | None = None,
        prompt_registry: PromptRegistry | None = None,
        prompt_version: str | None = None,
        settings: Settings | None = None,
        prompts_dir: Path = DEFAULT_PROMPTS_DIR,
    ) -> None:
        self._spec = spec
        self.name = spec.feature_name
        self.dataset_ref = spec.feature_name
        self._input_model = build_input_model(spec)
        self._output_model = build_output_model(spec)
        self._scorers: list[Scorer] = [build_scorer(s) for s in spec.scoring]

        self._client = client
        self._prompt_registry = prompt_registry
        self._prompt_version = prompt_version
        self._settings = settings
        self._prompts_dir = prompts_dir
        self._cached_prompt: LoadedPrompt | None = None

    # -- Feature contract -------------------------------------------------------

    @property
    def input_model(self) -> type[BaseModel]:
        return self._input_model

    @property
    def output_model(self) -> type[BaseModel]:
        return self._output_model

    def scorers(self) -> list[Scorer]:
        return list(self._scorers)

    def run(self, payload: BaseModel | Mapping[str, Any]) -> BaseModel:
        """Produce a validated structured output for a single input."""
        return self._invoke(payload).parsed

    def run_with_usage(self, payload: BaseModel | Mapping[str, Any]) -> FeatureRunResult:
        """Run and report token usage."""
        result = self._invoke(payload)
        return FeatureRunResult(
            output=result.parsed,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            total_tokens=result.total_tokens,
        )

    # -- helpers ----------------------------------------------------------------

    def _invoke(self, payload: BaseModel | Mapping[str, Any]) -> LLMResult[BaseModel]:
        data = self._coerce_input(payload)
        prompt = self._resolve_prompt()
        messages = self._build_messages(prompt, data)
        client = self._get_client()
        model = self._resolve_settings().model
        try:
            return client.parse_structured(
                model=model, messages=messages, schema=self._output_model
            )
        except LLMError as exc:
            logger.error("%s LLM call failed: %s", self.name, exc)
            raise FeatureExecutionError(f"{self.name} failed: {exc}") from exc

    def _coerce_input(self, payload: BaseModel | Mapping[str, Any]) -> BaseModel:
        if isinstance(payload, self._input_model):
            return payload
        if isinstance(payload, Mapping):
            return self._input_model.model_validate(payload)
        if isinstance(payload, BaseModel):
            return self._input_model.model_validate(payload.model_dump())
        raise FeatureExecutionError(
            f"unsupported input type for {self.name}: {type(payload).__name__}"
        )

    def _build_messages(self, prompt: LoadedPrompt, data: BaseModel) -> list[LLMMessage]:
        messages: list[LLMMessage] = [
            LLMMessage(role="system", content=prompt.definition.system_prompt)
        ]
        for example in prompt.definition.few_shot_examples:
            messages.append(LLMMessage(role="user", content=example.input))
            messages.append(LLMMessage(role="assistant", content=example.output))
        messages.append(LLMMessage(role="user", content=self._render_input(data)))
        return messages

    @staticmethod
    def _render_input(data: BaseModel) -> str:
        """Render the input as the final user message.

        For a single text field, use it directly; otherwise serialise the input dict
        so multi-field inputs still produce a deterministic message.
        """
        dump = data.model_dump(mode="json")
        string_values = [v for v in dump.values() if isinstance(v, str)]
        if len(string_values) == 1:
            return string_values[0]
        return json.dumps(dump, sort_keys=True)

    def _resolve_prompt(self) -> LoadedPrompt:
        if self._cached_prompt is not None:
            return self._cached_prompt
        registry = self._prompt_registry or PromptRegistry.from_directory(self._prompts_dir)
        feature = self._spec.resolved_prompt_feature
        prompt = (
            registry.get(feature, self._prompt_version)
            if self._prompt_version
            else registry.get_latest(feature)
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
                f"OPENAI_API_KEY is not set; cannot run {self.name} against OpenAI."
            )
        from mrds.llm.openai_client import OpenAIStructuredClient

        self._client = OpenAIStructuredClient(api_key=settings.openai_api_key)
        return self._client


def build_from_spec(
    spec: FeatureSpec,
    *,
    client: StructuredLLMClient | None = None,
    prompt_registry: PromptRegistry | None = None,
    prompts_dir: Path = DEFAULT_PROMPTS_DIR,
) -> GenericStructuredFeature:
    """Construct a :class:`GenericStructuredFeature` from a validated spec.

    Mints a per-spec subclass carrying ``name``/``dataset_ref`` as **class** attributes,
    because the feature registry reads the name off the class (``type(feature).name``) —
    matching how hand-coded features declare their `ClassVar` identity.
    """
    feature_cls = type(
        f"SpecFeature_{spec.feature_name}",
        (GenericStructuredFeature,),
        {"name": spec.feature_name, "dataset_ref": spec.feature_name},
    )
    return feature_cls(
        spec, client=client, prompt_registry=prompt_registry, prompts_dir=prompts_dir
    )
