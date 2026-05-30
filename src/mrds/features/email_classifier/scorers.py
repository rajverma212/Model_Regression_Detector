"""Scorers for the email-classification feature.

These are pure, deterministic, dependency-free scorers (no LLM, no network). They
implement the :class:`~mrds.core.interfaces.Scorer` protocol and are consumed by
the evaluation engine in Sprint 5. Optional LLM-as-judge scoring is added later
and stays off by default for cost control.
"""

from __future__ import annotations

import re

from pydantic import BaseModel

from mrds.core.interfaces import ScoreResult
from mrds.features.email_classifier.schema import EmailClassificationOutput

# Heuristic bounds for an acceptable one-sentence summary.
_MIN_WORDS = 3
_MAX_WORDS = 40
_SENTENCE_SPLIT = re.compile(r"[.!?]+")


def _as_output(value: BaseModel) -> EmailClassificationOutput:
    if not isinstance(value, EmailClassificationOutput):
        raise TypeError(f"expected EmailClassificationOutput, got {type(value).__name__}")
    return value


class CategoryMatchScorer:
    """Exact-match scorer for the ``category`` field."""

    name = "category_match"

    def score(self, actual: BaseModel, expected: BaseModel) -> ScoreResult:
        actual_out = _as_output(actual)
        expected_out = _as_output(expected)
        matched = actual_out.category == expected_out.category
        return ScoreResult(
            name=self.name,
            score=1.0 if matched else 0.0,
            passed=matched,
            detail=(
                "category matched"
                if matched
                else f"expected '{expected_out.category.value}', got '{actual_out.category.value}'"
            ),
        )


class SummaryQualityScorer:
    """Heuristic scorer: summary is non-empty and roughly a single sentence."""

    name = "summary_quality"

    def score(self, actual: BaseModel, expected: BaseModel) -> ScoreResult:
        actual_out = _as_output(actual)
        text = actual_out.summary.strip()
        sentences = [s for s in _SENTENCE_SPLIT.split(text) if s.strip()]
        word_count = len(text.split())

        passed = bool(text) and len(sentences) <= 1 and _MIN_WORDS <= word_count <= _MAX_WORDS
        return ScoreResult(
            name=self.name,
            score=1.0 if passed else 0.0,
            passed=passed,
            detail=f"words={word_count}, sentences={len(sentences)}",
        )
