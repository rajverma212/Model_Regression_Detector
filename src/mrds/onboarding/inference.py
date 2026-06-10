"""Infer a :class:`FeatureSpec` from a labeled dataset (Classification / Routing).

Pure, dependency-light: given the raw dataset (the standard ``{"cases": [...]}`` shape
or a bare list of cases), propose input/output fields, enum value sets, ``exact_match``
scoring per categorical output, and a segment field. The proposal is meant to be
*confirmed* by the user; the heuristics below are intentionally simple.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum

from mrds.features.spec import FeatureSpec, FieldSpec, FieldType, ScorerKind, ScorerSpec
from mrds.onboarding.errors import OnboardingError

# Heuristic bounds for treating a string output field as a categorical enum.
_ENUM_MAX_DISTINCT = 12
_ENUM_MAX_VALUE_LEN = 40


class FeatureFamily(StrEnum):
    """Supported families for the onboarding MVP."""

    CLASSIFICATION = "classification"
    ROUTING = "routing"


def _coerce_family(feature_type: str | FeatureFamily) -> FeatureFamily:
    try:
        return FeatureFamily(feature_type)
    except ValueError as exc:
        supported = ", ".join(f.value for f in FeatureFamily)
        raise OnboardingError(
            f"unsupported feature_type '{feature_type}'; expected one of: {supported}"
        ) from exc


def _cases(raw_dataset: object) -> list[dict]:
    if isinstance(raw_dataset, dict) and "cases" in raw_dataset:
        cases = raw_dataset["cases"]
    elif isinstance(raw_dataset, list):
        cases = raw_dataset
    else:
        raise OnboardingError("dataset must be a list of cases or an object with a 'cases' list")
    if not isinstance(cases, list) or not cases:
        raise OnboardingError("dataset must contain at least one case")

    seen_ids: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise OnboardingError(f"case #{index} is not an object")
        case_id = case.get("id")
        if not case_id:
            raise OnboardingError(f"case #{index} is missing an 'id'")
        if case_id in seen_ids:
            raise OnboardingError(f"duplicate case id: {case_id!r}")
        seen_ids.add(case_id)
        if not isinstance(case.get("input"), dict) or not case["input"]:
            raise OnboardingError(f"case '{case_id}' is missing a non-empty 'input'")
        if not isinstance(case.get("expected_output"), dict) or not case["expected_output"]:
            raise OnboardingError(f"case '{case_id}' is missing a non-empty 'expected_output'")
    return cases


def _ordered_keys(dicts: Sequence[dict]) -> list[str]:
    keys: list[str] = []
    for mapping in dicts:
        for key in mapping:
            if key not in keys:
                keys.append(key)
    return keys


def _infer_type(values: Sequence[object], *, allow_enum: bool) -> tuple[FieldType, list[str]]:
    present = [v for v in values if v is not None]
    if not present:
        return FieldType.STRING, []
    if all(isinstance(v, bool) for v in present):
        return FieldType.BOOLEAN, []
    if all(isinstance(v, int) and not isinstance(v, bool) for v in present):
        return FieldType.INTEGER, []
    if all(isinstance(v, int | float) and not isinstance(v, bool) for v in present):
        return FieldType.NUMBER, []
    if all(isinstance(v, str) for v in present):
        distinct = sorted(set(present))
        looks_categorical = (
            len(distinct) <= _ENUM_MAX_DISTINCT
            and max(len(v) for v in distinct) <= _ENUM_MAX_VALUE_LEN
        )
        if allow_enum and looks_categorical:
            return FieldType.ENUM, distinct
        return FieldType.STRING, []
    return FieldType.STRING, []


def _fields(cases: Sequence[dict], key: str, *, allow_enum: bool) -> list[FieldSpec]:
    dicts = [case[key] for case in cases]
    fields: list[FieldSpec] = []
    for name in _ordered_keys(dicts):
        values = [mapping.get(name) for mapping in dicts]
        field_type, enum_values = _infer_type(values, allow_enum=allow_enum)
        required = all(name in mapping for mapping in dicts)
        fields.append(FieldSpec(name=name, type=field_type, values=enum_values, required=required))
    return fields


def infer_feature_spec(
    raw_dataset: object,
    *,
    feature_name: str,
    feature_type: str | FeatureFamily,
) -> FeatureSpec:
    """Propose a :class:`FeatureSpec` from a labeled dataset.

    Categorical (enum) output fields are graded with ``exact_match``; the first enum
    output becomes the ``segment_field``. Requires at least one categorical output
    (Classification / Routing); raises :class:`OnboardingError` otherwise.
    """
    _coerce_family(feature_type)  # validates the family
    cases = _cases(raw_dataset)

    input_fields = _fields(cases, "input", allow_enum=False)
    output_fields = _fields(cases, "expected_output", allow_enum=True)

    enum_outputs = [f for f in output_fields if f.type is FieldType.ENUM]
    if not enum_outputs:
        raise OnboardingError(
            "no categorical (enum) output field detected; Classification/Routing requires "
            "at least one short, repeated label field to grade with exact_match"
        )

    scoring = [ScorerSpec(field=f.name, scorer=ScorerKind.EXACT_MATCH) for f in enum_outputs]

    try:
        return FeatureSpec(
            feature_name=feature_name,
            input_fields=input_fields,
            output_fields=output_fields,
            scoring=scoring,
            segment_field=enum_outputs[0].name,
        )
    except ValueError as exc:  # FeatureSpec validators
        raise OnboardingError(f"could not assemble a valid FeatureSpec: {exc}") from exc
