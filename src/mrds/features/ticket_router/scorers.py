"""Scorers for the support-ticket-routing feature.

Pure, deterministic, dependency-free scorers (no LLM, no network). They implement
the :class:`~mrds.core.interfaces.Scorer` protocol and are consumed by the shared
evaluation engine exactly like the email classifier's scorers.
"""

from __future__ import annotations

from pydantic import BaseModel

from mrds.core.interfaces import ScoreResult
from mrds.features.ticket_router.schema import TicketRoutingOutput


def _as_output(value: BaseModel) -> TicketRoutingOutput:
    if not isinstance(value, TicketRoutingOutput):
        raise TypeError(f"expected TicketRoutingOutput, got {type(value).__name__}")
    return value


class CategoryMatchScorer:
    """Exact-match scorer for the ``category`` (routing queue) field."""

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


class PriorityMatchScorer:
    """Exact-match scorer for the ``priority`` field."""

    name = "priority_match"

    def score(self, actual: BaseModel, expected: BaseModel) -> ScoreResult:
        actual_out = _as_output(actual)
        expected_out = _as_output(expected)
        matched = actual_out.priority == expected_out.priority
        return ScoreResult(
            name=self.name,
            score=1.0 if matched else 0.0,
            passed=matched,
            detail=(
                "priority matched"
                if matched
                else f"expected '{expected_out.priority.value}', got '{actual_out.priority.value}'"
            ),
        )
