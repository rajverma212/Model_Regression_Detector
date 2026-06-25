"""Provider-neutral types and the structured-output client protocol.

Keeping these provider-agnostic means features (and, later, the evaluation
engine) never import the Anthropic SDK directly — they depend on
:class:`StructuredLLMClient`, which any provider implementation can satisfy and
any test can fake.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Generic, Literal, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

Role = Literal["system", "developer", "user", "assistant"]


@dataclass(frozen=True)
class LLMMessage:
    """A single chat message in a structured-output request."""

    role: Role
    content: str


@dataclass(frozen=True)
class LLMResult(Generic[T]):
    """The result of a structured-output call: the parsed model plus token usage.

    Token usage is captured now (cheaply) so cost tracking in later sprints needs
    no client changes; cost computation itself is out of scope here.
    """

    parsed: T
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0


@runtime_checkable
class StructuredLLMClient(Protocol):
    """A client that returns a validated Pydantic model from a chat request."""

    def parse_structured(
        self,
        *,
        model: str,
        messages: Sequence[LLMMessage],
        schema: type[T],
    ) -> LLMResult[T]:
        """Call the model and return its output parsed into ``schema``."""
        ...
