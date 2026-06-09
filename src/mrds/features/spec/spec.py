"""Declarative feature-specification models.

A :class:`FeatureSpec` describes a structured-output feature (its input/output
fields, enum value sets, and which built-in scorer grades each field) **without any
Python per feature**. These are pure Pydantic models — no file I/O, no registry
side effects — so they can be validated and tested in isolation.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class SpecError(ValueError):
    """Raised when a feature specification is invalid or cannot be realized."""


class FieldType(StrEnum):
    """Supported declarative field types."""

    STRING = "string"
    INTEGER = "integer"
    NUMBER = "number"
    BOOLEAN = "boolean"
    ENUM = "enum"


class ScorerKind(StrEnum):
    """Built-in scorers selectable from a spec (Phase 1 library)."""

    EXACT_MATCH = "exact_match"
    TEXT_BOUNDS = "text_bounds"


class FieldSpec(BaseModel):
    """One input or output field declaration."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, description="Field name (becomes a model attribute).")
    type: FieldType = Field(default=FieldType.STRING, description="Declared field type.")
    values: list[str] = Field(
        default_factory=list, description="Allowed values; required iff type is 'enum'."
    )
    required: bool = Field(default=True, description="Whether the field must be present.")
    description: str = Field(default="", description="Optional human description.")

    @field_validator("name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("field name must not be blank")
        return value

    @model_validator(mode="after")
    def _values_match_type(self) -> FieldSpec:
        if self.type is FieldType.ENUM:
            if not self.values:
                raise ValueError(f"enum field '{self.name}' must declare non-empty values")
            if any(not v.strip() for v in self.values):
                raise ValueError(f"enum field '{self.name}' has a blank value")
            if len(set(self.values)) != len(self.values):
                raise ValueError(f"enum field '{self.name}' has duplicate values")
        elif self.values:
            raise ValueError(f"non-enum field '{self.name}' must not declare values")
        return self


class ScorerParams(BaseModel):
    """Parameters for parameterized scorers (currently ``text_bounds``)."""

    model_config = ConfigDict(extra="forbid")

    min_words: int | None = Field(default=None, ge=0)
    max_words: int | None = Field(default=None, ge=0)
    max_sentences: int | None = Field(default=None, ge=0)
    nonempty: bool = True


class ScorerSpec(BaseModel):
    """Binds one built-in scorer to one output field."""

    model_config = ConfigDict(extra="forbid")

    field: str = Field(min_length=1, description="Output field this scorer grades.")
    scorer: ScorerKind = Field(description="Which built-in scorer to use.")
    name: str | None = Field(default=None, description="Override the scorer's metric name.")
    params: ScorerParams = Field(default_factory=ScorerParams)


class FeatureSpec(BaseModel):
    """A complete declarative feature definition."""

    model_config = ConfigDict(extra="forbid")

    feature_name: str = Field(min_length=1, description="Stable feature id.")
    title: str = Field(default="", description="Optional display title.")
    description: str = Field(default="", description="Optional description.")
    input_fields: list[FieldSpec] = Field(min_length=1)
    output_fields: list[FieldSpec] = Field(min_length=1)
    scoring: list[ScorerSpec] = Field(min_length=1)
    segment_field: str | None = Field(
        default=None, description="Output field to segment metrics by."
    )
    prompt_feature: str | None = Field(
        default=None, description="Prompt directory to resolve from; defaults to feature_name."
    )

    @field_validator("feature_name")
    @classmethod
    def _name_not_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("feature_name must not be blank")
        return value

    @model_validator(mode="after")
    def _check_references(self) -> FeatureSpec:
        input_names = [f.name for f in self.input_fields]
        output_names = [f.name for f in self.output_fields]
        if len(set(input_names)) != len(input_names):
            raise ValueError("input field names must be unique")
        if len(set(output_names)) != len(output_names):
            raise ValueError("output field names must be unique")

        output_set = set(output_names)
        for entry in self.scoring:
            if entry.field not in output_set:
                raise ValueError(f"scoring references unknown output field '{entry.field}'")
        if self.segment_field is not None and self.segment_field not in output_set:
            raise ValueError(f"segment_field '{self.segment_field}' is not an output field")
        return self

    @property
    def resolved_prompt_feature(self) -> str:
        """The prompt directory to resolve from (``prompt_feature`` or ``feature_name``)."""
        return self.prompt_feature or self.feature_name
