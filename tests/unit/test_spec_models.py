"""Phase 1: dynamic model + enum generation from a FeatureSpec."""

from __future__ import annotations

from enum import Enum

import pytest
from pydantic import ValidationError

from mrds.features.spec import (
    FeatureSpec,
    FieldSpec,
    FieldType,
    ScorerKind,
    ScorerSpec,
    build_enum,
    build_input_model,
    build_output_model,
)
from mrds.features.spec.spec import SpecError  # noqa: F401  (ensures import works)


def _spec() -> FeatureSpec:
    return FeatureSpec(
        feature_name="demo_feature",
        input_fields=[FieldSpec(name="text", type=FieldType.STRING)],
        output_fields=[
            FieldSpec(name="label", type=FieldType.ENUM, values=["a", "b", "c"]),
            FieldSpec(name="score", type=FieldType.NUMBER, required=False),
        ],
        scoring=[ScorerSpec(field="label", scorer=ScorerKind.EXACT_MATCH)],
        segment_field="label",
    )


# -- enum generation ------------------------------------------------------------


def test_build_enum_values_preserved() -> None:
    enum = build_enum("Color", ["billing", "technical_support"])
    assert issubclass(enum, Enum)
    assert {m.value for m in enum} == {"billing", "technical_support"}


def test_build_enum_sanitises_member_names_without_losing_values() -> None:
    enum = build_enum("Weird", ["feature-request", "feature request"])
    # Member *names* are sanitised/deduped; the string *values* are exact.
    assert {m.value for m in enum} == {"feature-request", "feature request"}
    assert len(list(enum)) == 2


# -- output model ---------------------------------------------------------------


def test_output_model_accepts_valid_payload_and_coerces_enum() -> None:
    model = build_output_model(_spec())
    obj = model.model_validate({"label": "a", "score": 0.5})
    assert obj.label.value == "a"
    assert obj.score == 0.5


def test_output_model_optional_field_defaults_to_none() -> None:
    model = build_output_model(_spec())
    obj = model.model_validate({"label": "b"})
    assert obj.score is None


def test_output_model_rejects_unknown_enum_value() -> None:
    model = build_output_model(_spec())
    with pytest.raises(ValidationError):
        model.model_validate({"label": "z"})


def test_output_model_forbids_extra_keys() -> None:
    model = build_output_model(_spec())
    with pytest.raises(ValidationError):
        model.model_validate({"label": "a", "unexpected": 1})


def test_input_model_requires_required_field() -> None:
    model = build_input_model(_spec())
    assert model.model_validate({"text": "hello"}).text == "hello"
    with pytest.raises(ValidationError):
        model.model_validate({})


# -- spec validation ------------------------------------------------------------


def test_enum_field_requires_values() -> None:
    with pytest.raises(ValidationError):
        FieldSpec(name="label", type=FieldType.ENUM, values=[])


def test_non_enum_field_rejects_values() -> None:
    with pytest.raises(ValidationError):
        FieldSpec(name="text", type=FieldType.STRING, values=["a"])


def test_scoring_must_reference_an_output_field() -> None:
    with pytest.raises(ValidationError):
        FeatureSpec(
            feature_name="bad",
            input_fields=[FieldSpec(name="text")],
            output_fields=[FieldSpec(name="label", type=FieldType.ENUM, values=["a"])],
            scoring=[ScorerSpec(field="missing", scorer=ScorerKind.EXACT_MATCH)],
        )


def test_segment_field_must_be_an_output_field() -> None:
    with pytest.raises(ValidationError):
        FeatureSpec(
            feature_name="bad",
            input_fields=[FieldSpec(name="text")],
            output_fields=[FieldSpec(name="label", type=FieldType.ENUM, values=["a"])],
            scoring=[ScorerSpec(field="label", scorer=ScorerKind.EXACT_MATCH)],
            segment_field="nope",
        )


def test_resolved_prompt_feature_defaults_to_feature_name() -> None:
    assert _spec().resolved_prompt_feature == "demo_feature"
    spec = _spec().model_copy(update={"prompt_feature": "other"})
    assert spec.resolved_prompt_feature == "other"
