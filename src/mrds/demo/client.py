"""A deterministic, offline LLM client for demo data generation.

Implements the :class:`~mrds.llm.base.StructuredLLMClient` protocol with no network
and no Anthropic calls. Classifications come from an *oracle* (the dataset's expected
labels); a deterministic ``wrong_texts`` set is misclassified to control accuracy.
Token counts scale deterministically, and an optional simulated latency makes the
dashboard's latency charts non-trivial.
"""

from __future__ import annotations

import hashlib
import time
from collections.abc import Mapping, Sequence

from mrds.features.email_classifier import EmailCategory, EmailClassificationOutput
from mrds.llm.base import LLMMessage, LLMResult

_CATEGORIES: list[str] = [category.value for category in EmailCategory]


def _stable_int(text: str) -> int:
    """A process-stable hash (Python's built-in ``hash`` is salted per process)."""
    return int(hashlib.sha256(text.encode("utf-8")).hexdigest()[:8], 16)


def _wrong_category(correct: str) -> str:
    """Return a deterministic category different from ``correct``."""
    index = _CATEGORIES.index(correct)
    return _CATEGORIES[(index + 1) % len(_CATEGORIES)]


class DeterministicEmailClient:
    """Offline structured client whose behaviour is fully determined by its inputs."""

    def __init__(
        self,
        *,
        oracle: Mapping[str, str],
        wrong_texts: frozenset[str],
        summary: str,
        token_scale: float = 1.0,
        latency_ms: float = 0.0,
        jitter_ms: float = 8.0,
        simulate_latency: bool = False,
    ) -> None:
        self._oracle = oracle
        self._wrong_texts = wrong_texts
        self._summary = summary
        self._token_scale = token_scale
        self._latency_ms = latency_ms
        self._jitter_ms = jitter_ms
        self._simulate_latency = simulate_latency

    def parse_structured(
        self,
        *,
        model: str,
        messages: Sequence[LLMMessage],
        schema: type,
    ) -> LLMResult[EmailClassificationOutput]:
        text = messages[-1].content
        correct = self._oracle.get(text, EmailCategory.GENERAL.value)
        category = _wrong_category(correct) if text in self._wrong_texts else correct

        if self._simulate_latency and self._latency_ms > 0:
            jitter = (_stable_int(text) % max(int(self._jitter_ms), 1)) / 1000.0
            time.sleep(self._latency_ms / 1000.0 + jitter)

        input_tokens = round((20 + len(text) / 4) * self._token_scale)
        output_tokens = round((10 + len(self._summary) / 4) * self._token_scale)
        output = EmailClassificationOutput(category=EmailCategory(category), summary=self._summary)
        return LLMResult(
            parsed=output,
            model=model,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            total_tokens=input_tokens + output_tokens,
        )
