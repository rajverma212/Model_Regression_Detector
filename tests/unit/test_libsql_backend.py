"""Tests for the libSQL / Turso storage backend and its sqlite3-compatibility adapter.

Runs the full store/repository stack — and DB-native activation — over a local libSQL
file, proving a second engine works behind :class:`StorageBackend` with no change above
the persistence layer. Skipped if the optional ``libsql`` package is not installed.
"""

from __future__ import annotations

from collections.abc import Sequence

import pytest

pytest.importorskip("libsql")

from mrds.activation.lifecycle import activate_feature_from_store  # noqa: E402
from mrds.config.settings import Settings  # noqa: E402
from mrds.dashboard.data import DashboardData  # noqa: E402
from mrds.db import DbError, EvaluationStore, LibsqlBackend, create_backend  # noqa: E402
from mrds.db.backends.libsql import _Row  # noqa: E402
from mrds.llm.base import LLMMessage, LLMResult  # noqa: E402
from mrds.onboarding import infer_feature_spec  # noqa: E402

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
        {
            "id": "c4",
            "input": {"text": "send me an invoice"},
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


# -- the row adapter ------------------------------------------------------------


def test_row_supports_index_name_and_dict() -> None:
    row = _Row(["feature_name", "version"], ["email_classifier", "v1"])
    assert row[0] == "email_classifier"  # positional (PRAGMA/COUNT paths)
    assert row["version"] == "v1"  # by-name (repositories)
    assert dict(row) == {"feature_name": "email_classifier", "version": "v1"}  # model_validate path
    assert list(row) == ["email_classifier", "v1"]


# -- backend selection ----------------------------------------------------------


def test_factory_builds_libsql_backend_from_settings() -> None:
    backend = create_backend(Settings(storage_backend="libsql", database_path="ignored.db"))
    assert isinstance(backend, LibsqlBackend)
    assert backend.name == "libsql"


def test_factory_rejects_unknown_backend() -> None:
    # Settings' Literal already rejects bad names at construction; this covers the
    # factory's own defensive guard via a stand-in settings object.
    class _Settings:
        storage_backend = "nope"
        database_path = "x.db"
        libsql_sync_url = None
        libsql_auth_token = None

    with pytest.raises(DbError, match="unknown storage backend"):
        create_backend(_Settings())  # type: ignore[arg-type]


# -- full stack over libSQL -----------------------------------------------------


def test_libsql_backend_runs_activation_end_to_end(tmp_path) -> None:
    backend = LibsqlBackend(tmp_path / "eval.db")
    store = EvaluationStore(backend.connect())

    spec = infer_feature_spec(_RAW, feature_name="lib_feat", feature_type="classification")
    result = activate_feature_from_store(
        spec,
        cases=_RAW["cases"],
        system_prompt="Classify the message into one category. Respond as JSON.",
        store=store,
        client=_Stub(),
    )

    assert result.aggregate_metrics.total_cases == 4
    # The full bundle + run persisted and read back through the libSQL connection.
    data = DashboardData(store)
    assert "lib_feat" in data.features()
    assert [r.run_uuid for r in data.runs("lib_feat")] == [result.run_id]
    view = data.dataset_view("lib_feat")
    assert view is not None and view.case_count == 4

    # Baseline promotion (a write path through the transaction wrapper) works too.
    store.promote_baseline(result.run_id, promoted_by="test", note="first")
    assert data.active_baseline("lib_feat") is not None


def test_libsql_persists_across_reconnects(tmp_path) -> None:
    """Durability parity: a new connection to the same file sees prior writes."""
    db_file = tmp_path / "eval.db"
    store = EvaluationStore(LibsqlBackend(db_file).connect())
    spec = infer_feature_spec(_RAW, feature_name="persist_me", feature_type="classification")
    activate_feature_from_store(
        spec, cases=_RAW["cases"], system_prompt="Classify. JSON.", store=store, client=_Stub()
    )

    reopened = EvaluationStore(LibsqlBackend(db_file).connect())
    assert "persist_me" in DashboardData(reopened).features()
