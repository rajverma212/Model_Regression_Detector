"""Built-in, field-name-based scorer library for spec-driven features.

Each scorer implements the :class:`~mrds.core.interfaces.Scorer` protocol but reads
the graded field **by name** (``getattr``) rather than depending on a concrete output
class — so the same scorer works for any generated model. Phase 1 ships the minimum
needed for parity: ``exact_match`` and ``text_bounds``.
"""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel

from mrds.core.interfaces import Scorer, ScoreResult
from mrds.features.spec.spec import ScorerKind, ScorerSpec, SpecError

_SENTENCE_SPLIT = re.compile(r"[.!?]+")


def _value(raw: object) -> object:
    """Normalise enum members to their underlying value for comparison/display."""
    return raw.value if isinstance(raw, Enum) else raw


class ExactMatchScorer:
    """Exact-equality scorer for one field (enum or scalar)."""

    def __init__(self, field: str, *, name: str | None = None) -> None:
        self.field = field
        self.name = name or f"{field}_match"

    def score(self, actual: BaseModel, expected: BaseModel) -> ScoreResult:
        actual_value = _value(getattr(actual, self.field))
        expected_value = _value(getattr(expected, self.field))
        matched = actual_value == expected_value
        return ScoreResult(
            name=self.name,
            score=1.0 if matched else 0.0,
            passed=matched,
            detail=(
                f"{self.field} matched"
                if matched
                else f"expected '{expected_value}', got '{actual_value}'"
            ),
        )


class TextBoundsScorer:
    """Heuristic scorer: a text field is non-empty and within word/sentence bounds."""

    def __init__(
        self,
        field: str,
        *,
        name: str | None = None,
        min_words: int | None = None,
        max_words: int | None = None,
        max_sentences: int | None = None,
        nonempty: bool = True,
    ) -> None:
        self.field = field
        self.name = name or f"{field}_quality"
        self.min_words = min_words
        self.max_words = max_words
        self.max_sentences = max_sentences
        self.nonempty = nonempty

    def score(self, actual: BaseModel, expected: BaseModel) -> ScoreResult:
        text = str(getattr(actual, self.field) or "").strip()
        sentences = [s for s in _SENTENCE_SPLIT.split(text) if s.strip()]
        word_count = len(text.split())

        passed = True
        if self.nonempty and not text:
            passed = False
        if self.min_words is not None and word_count < self.min_words:
            passed = False
        if self.max_words is not None and word_count > self.max_words:
            passed = False
        if self.max_sentences is not None and len(sentences) > self.max_sentences:
            passed = False

        return ScoreResult(
            name=self.name,
            score=1.0 if passed else 0.0,
            passed=passed,
            detail=f"words={word_count}, sentences={len(sentences)}",
        )


def build_scorer(spec: ScorerSpec) -> Scorer:
    """Instantiate a library scorer from a :class:`ScorerSpec`."""
    if spec.scorer is ScorerKind.EXACT_MATCH:
        return ExactMatchScorer(spec.field, name=spec.name)
    if spec.scorer is ScorerKind.TEXT_BOUNDS:
        params = spec.params
        return TextBoundsScorer(
            spec.field,
            name=spec.name,
            min_words=params.min_words,
            max_words=params.max_words,
            max_sentences=params.max_sentences,
            nonempty=params.nonempty,
        )
    raise SpecError(f"unknown scorer kind: {spec.scorer}")  # pragma: no cover
