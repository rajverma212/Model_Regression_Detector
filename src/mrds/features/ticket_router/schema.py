"""Input/output schemas for the support-ticket-routing feature.

The output schema is the platform's structured-output contract for this feature:

    {"category": "billing | technical_support | account_access | feature_request",
     "priority": "low | medium | high"}
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class TicketCategory(StrEnum):
    """The four support-ticket routing categories (the destination queue)."""

    BILLING = "billing"
    TECHNICAL_SUPPORT = "technical_support"
    ACCOUNT_ACCESS = "account_access"
    FEATURE_REQUEST = "feature_request"


class TicketPriority(StrEnum):
    """How urgently the ticket should be handled."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class TicketRoutingInput(BaseModel):
    """A single inbound support ticket to route."""

    model_config = ConfigDict(extra="forbid")

    ticket_text: str = Field(min_length=1, description="Raw customer ticket text.")

    @field_validator("ticket_text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("ticket_text must not be blank")
        return value


class TicketRoutingOutput(BaseModel):
    """The structured routing decision."""

    model_config = ConfigDict(extra="forbid")

    category: TicketCategory = Field(description="The single best-fitting routing queue.")
    priority: TicketPriority = Field(description="The handling priority for the ticket.")
