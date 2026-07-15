"""Tests for the unified Create → Activate → Evaluate → View Results lifecycle (DB-native)."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from mrds.activation import ActivationError
from mrds.activation.lifecycle import activate_feature_from_store
from mrds.dashboard.data import DashboardData
from mrds.db import EvaluationStore, open_database
from mrds.llm.base import LLMMessage, LLMResult
from mrds.onboarding import infer_feature_spec

_RAW = {
    "cases": [
        {
            "id": "c1",
            "input": {"text": "please refund my charge"},
            "expected_output": {"category": "billing"},
        },
        {
            "id": "c2",
            "input": {"text": "the app keeps crashing"},
            "expected_output": {"category": "technical"},
        },
        {
            "id": "c3",
            "input": {"text": "i need to reset my password"},
            "expected_output": {"category": "account"},
        },
        {
            "id": "c4",
            "input": {"text": "send me this months invoice"},
            "expected_output": {"category": "billing"},
        },
    ]
}
_ORACLE = {c["input"]["text"]: c["expected_output"]["category"] for c in _RAW["cases"]}


class _Stub:
    def parse_structured(
        self, *, model: str, messages: Sequence[LLMMessage], schema: type
    ) -> LLMResult:
        label = _ORACLE.get(messages[-1].content, "billing")
        return LLMResult(
            parsed=schema.model_validate({"category": label}),
            model=model,
            input_tokens=5,
            output_tokens=2,
            total_tokens=7,
        )


def _spec(name: str):
    return infer_feature_spec(_RAW, feature_name=name, feature_type="classification")


def test_activate_feature_from_store_is_filesystem_free(tmp_path) -> None:
    spec = _spec("db_native")
    store = EvaluationStore(open_database(":memory:"))

    result = activate_feature_from_store(
        spec,
        cases=_RAW["cases"],
        system_prompt="Classify the message into one category. Respond as JSON.",
        store=store,
        client=_Stub(),
    )

    assert result.feature == "db_native"
    assert result.aggregate_metrics.total_cases == 4
    # The full bundle is persisted in the DB system of record (spec + prompt + dataset).
    assert store.feature_specs.get("db_native") is not None
    assert store.prompt_versions.all()[0].content
    assert store.dataset_versions.all()[0].content
    assert store.dataset_versions.all()[0].case_count == 4
    # The run is visible in Mission Control, and nothing was written to the filesystem.
    assert "db_native" in DashboardData(store).features()
    assert not any(tmp_path.iterdir())

    # Re-activation of an already-activated feature is rejected.
    with pytest.raises(ActivationError):
        activate_feature_from_store(
            spec, cases=_RAW["cases"], system_prompt="x", store=store, client=_Stub()
        )


def test_activate_succeeds_on_a_seeded_store() -> None:
    """Regression test (store-side twin of the shared-directory discovery bug): a store
    already holding *another* feature's dataset content — a different schema, as on the
    seeded production DB — must not break a new activation."""
    import json

    store = EvaluationStore(open_database(":memory:"))
    store.dataset_versions.upsert(
        feature_name="email_like",
        version="v1",
        content_hash="foreign-hash",
        case_count=1,
        content=json.dumps(
            {
                "version": "v1",
                "created_at": "2026-01-01",
                "description": "A foreign feature with a different schema.",
                "cases": [
                    {
                        "id": "e1",
                        "input": {"email_text": "I was charged twice."},
                        "expected_output": {"category": "billing", "summary": "Double charge."},
                        "expected_difficulty": "easy",
                        "notes": "",
                    }
                ],
            }
        ),
    )

    result = activate_feature_from_store(
        _spec("new_feat"),
        cases=_RAW["cases"],
        system_prompt="Classify the message into one category. Respond as JSON.",
        store=store,
        client=_Stub(),
    )
    assert result.aggregate_metrics.total_cases == 4
    assert "new_feat" in DashboardData(store).features()


def test_full_create_activate_evaluate_view() -> None:
    store = EvaluationStore(open_database(":memory:"))

    # Create + Activate + Evaluate (no filesystem).
    result = activate_feature_from_store(
        _spec("cust_router"),
        cases=_RAW["cases"],
        system_prompt="Classify the message into one category. Respond as JSON.",
        store=store,
        client=_Stub(),
    )

    # View Results (via DashboardData — what the dashboard/API render).
    data = DashboardData(store)
    detail = data.run_detail(result.run_id)

    assert "cust_router" in data.features()
    assert detail is not None
    assert set(detail.aggregate_metrics.scorers) == {"category_match"}
    assert set(detail.aggregate_metrics.segments) == {"account", "billing", "technical"}
    # The golden dataset is served from the DB, not the filesystem.
    view = data.dataset_view("cust_router")
    assert view is not None and view.case_count == 4
