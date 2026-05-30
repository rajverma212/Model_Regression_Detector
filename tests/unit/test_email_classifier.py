"""Tests for the email-classification feature (OpenAI fully mocked via a fake client)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest
from pydantic import BaseModel, ValidationError

from mrds.core.errors import FeatureExecutionError
from mrds.core.interfaces import Feature, ScoreResult
from mrds.features.email_classifier import (
    EmailCategory,
    EmailClassificationInput,
    EmailClassificationOutput,
    EmailClassifierFeature,
)
from mrds.features.email_classifier.scorers import CategoryMatchScorer, SummaryQualityScorer
from mrds.llm.base import LLMMessage, LLMResult
from mrds.llm.errors import LLMClientError, LLMConfigurationError
from mrds.prompts.registry import PromptRegistry

PROMPTS = PromptRegistry.from_directory(Path("prompts"))


class FakeClient:
    """A structural stand-in for StructuredLLMClient that records its inputs."""

    def __init__(self, output: EmailClassificationOutput) -> None:
        self._output = output
        self.captured_messages: list[LLMMessage] = []
        self.captured_model: str | None = None

    def parse_structured(
        self, *, model: str, messages: Sequence[LLMMessage], schema: type[BaseModel]
    ) -> LLMResult[EmailClassificationOutput]:
        self.captured_model = model
        self.captured_messages = list(messages)
        assert schema is EmailClassificationOutput
        return LLMResult(parsed=self._output, model=model, total_tokens=42)


class BoomClient:
    """A client that always fails, to exercise error handling."""

    def parse_structured(self, **_: object) -> LLMResult[EmailClassificationOutput]:
        raise LLMClientError("boom")


def _feature(client: object) -> EmailClassifierFeature:
    return EmailClassifierFeature(client=client, prompt_registry=PROMPTS)  # type: ignore[arg-type]


# -- schema / structured-output validation --------------------------------------


def test_output_schema_valid() -> None:
    out = EmailClassificationOutput(category="billing", summary="A refund request.")
    assert out.category is EmailCategory.BILLING


def test_output_rejects_invalid_category() -> None:
    with pytest.raises(ValidationError):
        EmailClassificationOutput(category="spam", summary="x")


def test_output_forbids_extra_fields() -> None:
    with pytest.raises(ValidationError):
        EmailClassificationOutput(category="general", summary="hi", confidence=0.9)


def test_input_rejects_blank() -> None:
    with pytest.raises(ValidationError):
        EmailClassificationInput(email_text="   ")


# -- feature contract / registry ------------------------------------------------


def test_feature_implements_contract() -> None:
    feature = EmailClassifierFeature()
    assert isinstance(feature, Feature)
    assert feature.name == "email_classifier"
    assert feature.dataset_ref == "email_classifier"
    assert feature.input_model is EmailClassificationInput
    assert feature.output_model is EmailClassificationOutput
    assert {s.name for s in feature.scorers()} == {"category_match", "summary_quality"}


# -- run() with a fake client ---------------------------------------------------


def test_run_returns_parsed_output_and_uses_loaded_prompt() -> None:
    expected = EmailClassificationOutput(category="technical", summary="App crashes on export.")
    client = FakeClient(expected)
    feature = _feature(client)

    result = feature.run(EmailClassificationInput(email_text="The app keeps crashing."))

    assert result == expected
    # No hardcoded prompt: the system message comes from the loaded prompt file.
    loaded = PROMPTS.get_latest("email_classifier")
    assert client.captured_messages[0].role == "system"
    assert client.captured_messages[0].content == loaded.definition.system_prompt
    # Few-shot examples from the prompt are included as user/assistant turns.
    assert any(m.role == "assistant" for m in client.captured_messages)
    # The email is the final user turn.
    assert client.captured_messages[-1].role == "user"
    assert client.captured_messages[-1].content == "The app keeps crashing."


def test_run_accepts_mapping_input() -> None:
    expected = EmailClassificationOutput(category="account", summary="Login fails after reset.")
    feature = _feature(FakeClient(expected))
    assert feature.run({"email_text": "I can't log in."}) == expected


def test_run_wraps_llm_errors() -> None:
    feature = _feature(BoomClient())
    with pytest.raises(FeatureExecutionError):
        feature.run(EmailClassificationInput(email_text="hello"))


def test_run_without_client_or_key_raises(clear_secret_env: None) -> None:
    feature = EmailClassifierFeature(prompt_registry=PROMPTS)
    with pytest.raises(LLMConfigurationError):
        feature.run(EmailClassificationInput(email_text="hello"))


# -- scorers --------------------------------------------------------------------


def test_category_match_scorer() -> None:
    scorer = CategoryMatchScorer()
    a = EmailClassificationOutput(category="billing", summary="Refund please.")
    same = EmailClassificationOutput(category="billing", summary="Different summary text.")
    other = EmailClassificationOutput(category="general", summary="Refund please.")

    hit: ScoreResult = scorer.score(a, same)
    miss: ScoreResult = scorer.score(a, other)
    assert hit.passed and hit.score == 1.0
    assert not miss.passed and miss.score == 0.0


def test_summary_quality_scorer() -> None:
    scorer = SummaryQualityScorer()
    good = EmailClassificationOutput(category="general", summary="Customer asks about pricing.")
    multi = EmailClassificationOutput(category="general", summary="One thing. Two things. Three.")

    assert scorer.score(good, good).passed
    assert not scorer.score(multi, multi).passed
