"""Phase 1: built-in scorer library (field-name based)."""

from __future__ import annotations

import pytest

from mrds.features.spec import (
    FeatureSpec,
    FieldSpec,
    FieldType,
    ScorerKind,
    ScorerParams,
    ScorerSpec,
    build_output_model,
    build_scorer,
)
from mrds.features.spec.scorers import ExactMatchScorer, TextBoundsScorer

# A generated output model with an enum field + a free-text field, to score against.
_SPEC = FeatureSpec(
    feature_name="demo",
    input_fields=[FieldSpec(name="text")],
    output_fields=[
        FieldSpec(name="category", type=FieldType.ENUM, values=["billing", "technical"]),
        FieldSpec(name="summary", type=FieldType.STRING),
    ],
    scoring=[ScorerSpec(field="category", scorer=ScorerKind.EXACT_MATCH)],
)
_OUT = build_output_model(_SPEC)


def _out(category: str, summary: str = "ok") -> object:
    return _OUT.model_validate({"category": category, "summary": summary})


# -- exact match ----------------------------------------------------------------


def test_exact_match_pass() -> None:
    scorer = ExactMatchScorer("category")
    result = scorer.score(_out("billing"), _out("billing"))
    assert result.name == "category_match"
    assert result.passed and result.score == 1.0
    assert result.detail == "category matched"


def test_exact_match_fail_uses_enum_values_in_detail() -> None:
    result = ExactMatchScorer("category").score(_out("technical"), _out("billing"))
    assert not result.passed and result.score == 0.0
    assert result.detail == "expected 'billing', got 'technical'"


def test_exact_match_name_override() -> None:
    assert ExactMatchScorer("category", name="routing").name == "routing"


# -- text bounds ----------------------------------------------------------------


def _text_scorer() -> TextBoundsScorer:
    # Mirrors the email summary heuristic: 3..40 words, <=1 sentence, non-empty.
    return TextBoundsScorer("summary", min_words=3, max_words=40, max_sentences=1, nonempty=True)


def test_text_bounds_pass_within_bounds() -> None:
    result = _text_scorer().score(_out("billing", "A concise three word"), _out("billing"))
    assert result.passed
    assert result.name == "summary_quality"
    assert "words=4" in result.detail


def test_text_bounds_fail_when_empty() -> None:
    assert not _text_scorer().score(_out("billing", "   "), _out("billing")).passed


def test_text_bounds_fail_when_too_few_words() -> None:
    assert not _text_scorer().score(_out("billing", "tiny"), _out("billing")).passed


def test_text_bounds_fail_when_multiple_sentences() -> None:
    multi = "This is one. This is two."
    assert not _text_scorer().score(_out("billing", multi), _out("billing")).passed


# -- factory --------------------------------------------------------------------


def test_build_scorer_exact_match() -> None:
    scorer = build_scorer(ScorerSpec(field="category", scorer=ScorerKind.EXACT_MATCH))
    assert isinstance(scorer, ExactMatchScorer)
    assert scorer.name == "category_match"


def test_build_scorer_text_bounds_passes_params() -> None:
    spec = ScorerSpec(
        field="summary",
        scorer=ScorerKind.TEXT_BOUNDS,
        params=ScorerParams(min_words=3, max_words=40, max_sentences=1),
    )
    scorer = build_scorer(spec)
    assert isinstance(scorer, TextBoundsScorer)
    assert scorer.min_words == 3 and scorer.max_words == 40 and scorer.max_sentences == 1


@pytest.mark.parametrize("kind", [ScorerKind.EXACT_MATCH, ScorerKind.TEXT_BOUNDS])
def test_build_scorer_returns_named_scorer(kind: ScorerKind) -> None:
    scorer = build_scorer(ScorerSpec(field="category", scorer=kind))
    assert isinstance(scorer.name, str) and scorer.name
