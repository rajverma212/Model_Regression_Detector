"""Engine tests with a fake feature/dataset, plus a real email-classifier integration test."""

from __future__ import annotations

import json
from collections.abc import Sequence
from pathlib import Path

import pytest
from pydantic import BaseModel

from mrds.core.interfaces import Feature, Scorer, ScoreResult
from mrds.core.registry import FeatureRegistry
from mrds.datasets.registry import DatasetRegistry
from mrds.evaluation import EvaluationConfig, EvaluationEngine
from mrds.features.email_classifier import (
    EmailCategory,
    EmailClassificationOutput,
    EmailClassifierFeature,
)
from mrds.llm.base import LLMMessage, LLMResult
from mrds.prompts.registry import PromptRegistry

# ---------------------------------------------------------------------------
# A completely independent fake feature, to prove the engine is feature-agnostic.
# ---------------------------------------------------------------------------


class SentimentInput(BaseModel):
    text: str


class SentimentOutput(BaseModel):
    label: str


class LabelMatchScorer:
    name = "label_match"

    def score(self, actual: BaseModel, expected: BaseModel) -> ScoreResult:
        ok = actual.label == expected.label  # type: ignore[attr-defined]
        return ScoreResult(name=self.name, score=1.0 if ok else 0.0, passed=ok)


class FakeSentimentFeature(Feature):
    """A minimal feature implemented without any LLM."""

    name = "sentiment"
    dataset_ref = "sentiment"

    def __init__(self, table: dict[str, str]) -> None:
        self._table = table

    @property
    def input_model(self) -> type[BaseModel]:
        return SentimentInput

    @property
    def output_model(self) -> type[BaseModel]:
        return SentimentOutput

    def run(self, payload: BaseModel) -> SentimentOutput:
        return SentimentOutput(label=self._table.get(payload.text, "neg"))  # type: ignore[attr-defined]

    def scorers(self) -> list[Scorer]:
        return [LabelMatchScorer()]


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _build_fake_registries(
    tmp_path: Path,
) -> tuple[FeatureRegistry, PromptRegistry, DatasetRegistry]:
    # Feature
    feature = FakeSentimentFeature({"I love it": "pos", "Terrible": "neg"})
    features = FeatureRegistry()
    features.register(feature)  # type: ignore[arg-type]

    # Prompt (the engine resolves it for reproducibility metadata)
    prompt_dir = tmp_path / "prompts" / "sentiment"
    prompt_dir.mkdir(parents=True)
    (prompt_dir / "v1.yaml").write_text(
        "version: v1\ncreated_at: 2026-01-01\ndescription: d\nsystem_prompt: classify\n",
        encoding="utf-8",
    )
    prompts = PromptRegistry.from_directory(tmp_path / "prompts")

    # Dataset
    dataset = {
        "version": "v1",
        "created_at": "2026-01-01",
        "description": "sentiment golden set",
        "cases": [
            {
                "id": "s-1",
                "input": {"text": "I love it"},
                "expected_output": {"label": "pos"},
                "expected_difficulty": "easy",
            },
            {
                "id": "s-2",
                "input": {"text": "Terrible"},
                "expected_output": {"label": "neg"},
                "expected_difficulty": "easy",
            },
            {
                "id": "s-3",
                "input": {"text": "Unknown phrase"},
                "expected_output": {"label": "pos"},
                "expected_difficulty": "hard",
            },
        ],
    }
    _write_json(tmp_path / "datasets" / "sentiment" / "v1.json", dataset)
    datasets = DatasetRegistry.from_directory(
        tmp_path / "datasets", model_resolver=lambda _f: (SentimentInput, SentimentOutput)
    )
    return features, prompts, datasets


def test_engine_runs_fake_feature(tmp_path: Path) -> None:
    features, prompts, datasets = _build_fake_registries(tmp_path)
    engine = EvaluationEngine(features=features, prompts=prompts, datasets=datasets)

    result = engine.run(EvaluationConfig(feature="sentiment", segment_field="label"))

    assert result.feature == "sentiment"
    assert result.prompt_version == "v1"
    assert result.dataset_version == "v1"
    assert result.aggregate_metrics.total_cases == 3
    # s-1 and s-2 match; s-3 maps to "neg" but expects "pos" -> fail
    assert result.aggregate_metrics.passed == 2
    assert result.aggregate_metrics.failed == 1
    assert result.aggregate_metrics.scorers["label_match"].mean_score == pytest.approx(2 / 3)
    assert set(result.aggregate_metrics.segments) == {"pos", "neg"}
    assert result.run_id and result.duration_seconds >= 0


def test_engine_respects_max_cases(tmp_path: Path) -> None:
    features, prompts, datasets = _build_fake_registries(tmp_path)
    engine = EvaluationEngine(features=features, prompts=prompts, datasets=datasets)
    result = engine.run(EvaluationConfig(feature="sentiment", max_cases=1))
    assert result.aggregate_metrics.total_cases == 1


def test_engine_records_errored_case_without_aborting(tmp_path: Path) -> None:
    features, prompts, datasets = _build_fake_registries(tmp_path)

    class BoomFeature(FakeSentimentFeature):
        def run(self, payload: BaseModel) -> SentimentOutput:
            raise RuntimeError("kaboom")

    features = FeatureRegistry()
    features.register(BoomFeature({}))  # type: ignore[arg-type]
    engine = EvaluationEngine(features=features, prompts=prompts, datasets=datasets)

    result = engine.run(EvaluationConfig(feature="sentiment"))
    assert result.aggregate_metrics.errored == 3
    assert result.aggregate_metrics.passed == 0
    assert all(c.error for c in result.per_case_results)


def test_engine_raises_when_max_cases_zero_after_slice() -> None:
    # max_cases must be >= 1 by config validation; an empty dataset would raise.
    with pytest.raises(ValueError):
        EvaluationConfig(feature="sentiment", max_cases=0)


# ---------------------------------------------------------------------------
# Real email-classifier integration test (OpenAI faked via a keyword heuristic).
# ---------------------------------------------------------------------------


class HeuristicEmailClient:
    """A fake StructuredLLMClient that classifies via simple keyword rules."""

    def parse_structured(
        self, *, model: str, messages: Sequence[LLMMessage], schema: type[BaseModel]
    ) -> LLMResult[EmailClassificationOutput]:
        text = messages[-1].content.lower()
        if any(w in text for w in ("charge", "refund", "invoice", "price", "billed", "payment")):
            category = EmailCategory.BILLING
        elif any(w in text for w in ("password", "log in", "login", "account", "locked", "2fa")):
            category = EmailCategory.ACCOUNT
        elif any(w in text for w in ("crash", "error", "broken", "bug", "freez", "404", "500")):
            category = EmailCategory.TECHNICAL
        else:
            category = EmailCategory.GENERAL
        out = EmailClassificationOutput(
            category=category, summary="This is a heuristic classification."
        )
        return LLMResult(parsed=out, model=model, input_tokens=8, output_tokens=4, total_tokens=12)


def test_real_email_classifier_integration() -> None:
    prompts = PromptRegistry.from_directory(Path("prompts"))
    # Default (registry-based) resolver — the datasets dir is multi-feature.
    datasets = DatasetRegistry.from_directory(Path("datasets"))
    feature = EmailClassifierFeature(client=HeuristicEmailClient(), prompt_registry=prompts)
    features = FeatureRegistry()
    features.register(feature)

    engine = EvaluationEngine(features=features, prompts=prompts, datasets=datasets)
    result = engine.run(EvaluationConfig(feature="email_classifier", segment_field="category"))

    metrics = result.aggregate_metrics
    assert metrics.total_cases >= 50
    assert metrics.errored == 0
    # Required metrics are present and feature-agnostic (keyed by scorer name).
    assert "category_match" in metrics.scorers
    assert "summary_quality" in metrics.scorers
    assert metrics.scorers["summary_quality"].mean_score == pytest.approx(1.0)
    # Per-category accuracy is available for all four categories.
    assert set(metrics.segments) == {c.value for c in EmailCategory}
    # Token usage flows through run_with_usage.
    assert metrics.tokens.total_tokens == metrics.total_cases * 12
    # The heuristic should beat random chance on this human-authored set.
    assert metrics.scorers["category_match"].mean_score > 0.5
    assert result.prompt_version == "v1"
    assert result.dataset_version == "v1"
