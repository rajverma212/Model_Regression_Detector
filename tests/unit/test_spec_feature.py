"""Phase 1: GenericStructuredFeature satisfies the Feature contract (offline)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from mrds.core.interfaces import Feature
from mrds.features.spec import (
    FeatureSpec,
    FieldSpec,
    FieldType,
    GenericStructuredFeature,
    ScorerKind,
    ScorerSpec,
    build_from_spec,
)
from mrds.llm.base import LLMMessage, LLMResult
from mrds.prompts.registry import PromptRegistry

_PROMPT_YAML = """\
version: v1
created_at: 2026-06-07
description: Demo prompt for the spec-driven feature test.
system_prompt: |
  Classify the input into a label.
"""


def _spec() -> FeatureSpec:
    return FeatureSpec(
        feature_name="demo_feature",
        input_fields=[FieldSpec(name="text", type=FieldType.STRING)],
        output_fields=[FieldSpec(name="label", type=FieldType.ENUM, values=["a", "b"])],
        scoring=[ScorerSpec(field="label", scorer=ScorerKind.EXACT_MATCH)],
        segment_field="label",
    )


@pytest.fixture
def prompt_registry(tmp_path: Path) -> PromptRegistry:
    feature_dir = tmp_path / "demo_feature"
    feature_dir.mkdir()
    (feature_dir / "v1.yaml").write_text(_PROMPT_YAML, encoding="utf-8")
    return PromptRegistry.from_directory(tmp_path)


class _StubClient:
    """Deterministic offline client returning a fixed validated output."""

    def __init__(self, values: dict[str, str]) -> None:
        self._values = values

    def parse_structured(
        self, *, model: str, messages: Sequence[LLMMessage], schema: type
    ) -> LLMResult:
        parsed = schema.model_validate(self._values)
        return LLMResult(
            parsed=parsed, model=model, input_tokens=7, output_tokens=3, total_tokens=10
        )


def _feature(prompt_registry: PromptRegistry, label: str = "a") -> GenericStructuredFeature:
    return build_from_spec(
        _spec(), client=_StubClient({"label": label}), prompt_registry=prompt_registry
    )


def test_is_a_feature_with_spec_identity(prompt_registry: PromptRegistry) -> None:
    feature = _feature(prompt_registry)
    assert isinstance(feature, Feature)
    assert feature.name == "demo_feature"
    assert feature.dataset_ref == "demo_feature"


def test_generated_models_exposed(prompt_registry: PromptRegistry) -> None:
    feature = _feature(prompt_registry)
    inp = feature.input_model.model_validate({"text": "hello"})
    assert inp.text == "hello"
    out = feature.output_model.model_validate({"label": "a"})
    assert out.label.value == "a"


def test_scorers_wired_from_spec(prompt_registry: PromptRegistry) -> None:
    scorers = _feature(prompt_registry).scorers()
    assert [s.name for s in scorers] == ["label_match"]


def test_run_with_usage_returns_output_and_tokens(prompt_registry: PromptRegistry) -> None:
    feature = _feature(prompt_registry, label="b")
    result = feature.run_with_usage(feature.input_model.model_validate({"text": "hi"}))
    assert isinstance(result.output, feature.output_model)
    assert result.output.label.value == "b"
    assert result.total_tokens == 10


def test_run_returns_parsed_output(prompt_registry: PromptRegistry) -> None:
    feature = _feature(prompt_registry)
    out = feature.run({"text": "hi"})  # accepts a Mapping
    assert isinstance(out, feature.output_model)
    assert out.label.value == "a"


def test_end_to_end_score_of_a_case(prompt_registry: PromptRegistry) -> None:
    feature = _feature(prompt_registry, label="a")
    actual = feature.run({"text": "anything"})
    expected = feature.output_model.model_validate({"label": "a"})
    [scorer] = feature.scorers()
    assert scorer.score(actual, expected).passed
