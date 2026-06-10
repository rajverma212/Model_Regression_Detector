"""Tests for onboarding schema inference."""

from __future__ import annotations

import pytest

from mrds.features.spec import FieldType
from mrds.onboarding import OnboardingError, infer_feature_spec

_CLASSIFICATION = {
    "cases": [
        {
            "id": "c1",
            "input": {"text": "please refund my charge"},
            "expected_output": {"category": "billing"},
        },
        {
            "id": "c2",
            "input": {"text": "send me an invoice"},
            "expected_output": {"category": "billing"},
        },
        {
            "id": "c3",
            "input": {"text": "the app crashes on launch"},
            "expected_output": {"category": "technical"},
        },
        {
            "id": "c4",
            "input": {"text": "error on the login page"},
            "expected_output": {"category": "technical"},
        },
        {
            "id": "c5",
            "input": {"text": "reset my password"},
            "expected_output": {"category": "account"},
        },
        {
            "id": "c6",
            "input": {"text": "change my email address"},
            "expected_output": {"category": "account"},
        },
    ]
}

_ROUTING = {
    "cases": [
        {
            "id": "r1",
            "input": {"text": "double charged"},
            "expected_output": {"queue": "billing", "priority": "high"},
        },
        {
            "id": "r2",
            "input": {"text": "invoice copy"},
            "expected_output": {"queue": "billing", "priority": "low"},
        },
        {
            "id": "r3",
            "input": {"text": "500 error"},
            "expected_output": {"queue": "technical", "priority": "high"},
        },
        {
            "id": "r4",
            "input": {"text": "dark mode bug"},
            "expected_output": {"queue": "technical", "priority": "low"},
        },
    ]
}


def test_classification_inference() -> None:
    spec = infer_feature_spec(
        _CLASSIFICATION, feature_name="support_cls", feature_type="classification"
    )
    assert spec.feature_name == "support_cls"
    assert [f.name for f in spec.input_fields] == ["text"]
    assert spec.input_fields[0].type is FieldType.STRING
    [out] = spec.output_fields
    assert out.name == "category" and out.type is FieldType.ENUM
    assert out.values == ["account", "billing", "technical"]  # sorted distinct
    assert [(s.field, s.scorer.value) for s in spec.scoring] == [("category", "exact_match")]
    assert spec.segment_field == "category"


def test_routing_inference_multiple_enums() -> None:
    spec = infer_feature_spec(_ROUTING, feature_name="router", feature_type="routing")
    assert [f.name for f in spec.output_fields] == ["queue", "priority"]
    assert all(f.type is FieldType.ENUM for f in spec.output_fields)
    assert {s.field for s in spec.scoring} == {"queue", "priority"}
    assert spec.segment_field == "queue"  # first enum output


def test_numeric_output_is_typed_but_not_scored() -> None:
    raw = {
        "cases": [
            {"id": "m1", "input": {"text": "x"}, "expected_output": {"label": "a", "score": 0.9}},
            {"id": "m2", "input": {"text": "y"}, "expected_output": {"label": "b", "score": 0.2}},
        ]
    }
    spec = infer_feature_spec(raw, feature_name="mixed", feature_type="classification")
    by_name = {f.name: f for f in spec.output_fields}
    assert by_name["label"].type is FieldType.ENUM
    assert by_name["score"].type is FieldType.NUMBER
    # Only the enum field is scored (numeric scoring is a deferred library addition).
    assert [s.field for s in spec.scoring] == ["label"]


def test_free_text_only_output_is_rejected() -> None:
    raw = {
        "cases": [
            {
                "id": "f1",
                "input": {"text": "q1"},
                "expected_output": {
                    "answer": "Reset your password from the account settings page."
                },
            },
            {
                "id": "f2",
                "input": {"text": "q2"},
                "expected_output": {"answer": "Refunds go back to your original payment method."},
            },
        ]
    }
    with pytest.raises(OnboardingError, match="categorical"):
        infer_feature_spec(raw, feature_name="qa", feature_type="classification")


@pytest.mark.parametrize(
    "raw",
    [
        {"cases": []},
        {"cases": [{"id": "x", "input": {}, "expected_output": {"category": "billing"}}]},
        {"cases": [{"id": "x", "input": {"text": "hi"}, "expected_output": {}}]},
        {"cases": [{"input": {"text": "hi"}, "expected_output": {"category": "billing"}}]},  # no id
        [],  # empty list
    ],
)
def test_malformed_datasets_raise(raw: object) -> None:
    with pytest.raises(OnboardingError):
        infer_feature_spec(raw, feature_name="bad", feature_type="classification")


def test_duplicate_case_id_raises() -> None:
    raw = {
        "cases": [
            {"id": "dup", "input": {"text": "a"}, "expected_output": {"category": "billing"}},
            {"id": "dup", "input": {"text": "b"}, "expected_output": {"category": "technical"}},
        ]
    }
    with pytest.raises(OnboardingError, match="duplicate"):
        infer_feature_spec(raw, feature_name="bad", feature_type="classification")


def test_unsupported_feature_type_raises() -> None:
    with pytest.raises(OnboardingError, match="unsupported feature_type"):
        infer_feature_spec(_CLASSIFICATION, feature_name="x", feature_type="rag")
