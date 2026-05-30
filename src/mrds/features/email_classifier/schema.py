"""Input/output schemas for the email-classification feature.

The output schema is the platform's structured-output contract for this feature:

    {"category": "billing | technical | account | general",
     "summary": "one sentence summary"}
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class EmailCategory(StrEnum):
    """The four supported support-email categories."""

    BILLING = "billing"
    TECHNICAL = "technical"
    ACCOUNT = "account"
    GENERAL = "general"


class EmailClassificationInput(BaseModel):
    """A single customer support email to classify."""

    model_config = ConfigDict(extra="forbid")

    email_text: str = Field(min_length=1, description="Raw customer email text.")

    @field_validator("email_text")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("email_text must not be blank")
        return value


class EmailClassificationOutput(BaseModel):
    """The structured classification result."""

    model_config = ConfigDict(extra="forbid")

    category: EmailCategory = Field(description="The single best-fitting category.")
    summary: str = Field(min_length=1, description="One-sentence summary of the email.")

    @field_validator("summary")
    @classmethod
    def _not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("summary must not be blank")
        return value
