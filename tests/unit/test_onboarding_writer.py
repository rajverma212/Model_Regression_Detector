"""Tests for the in-memory feature-bundle builders (DB-native activation)."""

from __future__ import annotations

import pytest

from mrds.onboarding import (
    OnboardingError,
    build_dataset_definition,
    build_prompt_definition,
    infer_feature_spec,
    scaffold_prompt,
)

_RAW = {
    "cases": [
        {
            "id": "c1",
            "input": {"text": "refund my charge"},
            "expected_output": {"category": "billing"},
        },
        {
            "id": "c2",
            "input": {"text": "the app crashes"},
            "expected_output": {"category": "technical"},
        },
        {
            "id": "c3",
            "input": {"text": "reset my password"},
            "expected_output": {"category": "account"},
        },
    ]
}


def _spec_and_prompt():
    spec = infer_feature_spec(_RAW, feature_name="support_cls", feature_type="classification")
    return spec, scaffold_prompt(spec, feature_type="classification")


def test_prompt_and_dataset_definitions_are_built_and_valid() -> None:
    spec, prompt = _spec_and_prompt()

    prompt_def = build_prompt_definition(spec, prompt)
    assert prompt_def.version == "v1"
    assert prompt_def.system_prompt.strip()

    dataset_def = build_dataset_definition(spec, _RAW["cases"])
    assert dataset_def.version == "v1"
    assert dataset_def.case_count == 3
    # Cases are typed against the feature's generated models (kept as validated cases).
    assert [c.id for c in dataset_def.cases] == ["c1", "c2", "c3"]


def test_blank_prompt_rejected() -> None:
    spec, _ = _spec_and_prompt()
    with pytest.raises(OnboardingError, match="must not be blank"):
        build_prompt_definition(spec, "   ")


def test_case_outside_schema_rejected() -> None:
    spec, _ = _spec_and_prompt()
    bad_cases = [
        {"id": "x", "input": {"text": "hi"}, "expected_output": {"category": "not_a_real_label"}},
    ]
    with pytest.raises(OnboardingError, match="does not match the schema"):
        build_dataset_definition(spec, bad_cases)
