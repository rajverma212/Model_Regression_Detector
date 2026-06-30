"""Unit tests for persisting dataset content in the database (Phase 4).

Cover the new ``dataset_versions.content`` column: the repository stores/reads content,
a dataset round-trips through the DB (validated against the feature's models), and a
DatasetRegistry can be rebuilt from the database (skipping metadata-only rows).
"""

from __future__ import annotations

import json

from pydantic import BaseModel

from mrds.activation.discovery import load_datasets_from_store
from mrds.datasets.loader import load_dataset_from_definition_json
from mrds.db import EvaluationStore, open_database


class _In(BaseModel):
    text: str


class _Out(BaseModel):
    category: str


def _resolver(_feature: str) -> tuple[type[BaseModel], type[BaseModel]]:
    return _In, _Out


_DATASET = {
    "version": "v1",
    "created_at": "2026-01-01",
    "description": "Test dataset.",
    "cases": [
        {
            "id": "c1",
            "input": {"text": "hello"},
            "expected_output": {"category": "a"},
            "expected_difficulty": "easy",
        }
    ],
}


def _store() -> EvaluationStore:
    return EvaluationStore(open_database(":memory:"))


def _loaded():
    return load_dataset_from_definition_json(
        json.dumps(_DATASET), input_model=_In, output_model=_Out, feature="demo"
    )


def test_load_dataset_from_definition_json_roundtrips() -> None:
    loaded = _loaded()
    assert loaded.feature == "demo"
    assert loaded.case_count == 1
    assert str(loaded.source_path) == "db:/demo/v1"
    # Re-dump and reload: identity (content hash) is stable.
    again = load_dataset_from_definition_json(
        loaded.definition.model_dump_json(), input_model=_In, output_model=_Out, feature="demo"
    )
    assert again.content_hash == loaded.content_hash


def test_repository_upsert_persists_content() -> None:
    store = _store()
    loaded = _loaded()
    content = loaded.definition.model_dump_json()
    with store._db.transaction():
        record = store.dataset_versions.upsert(
            feature_name="demo",
            version="v1",
            content_hash=loaded.content_hash,
            case_count=loaded.case_count,
            content=content,
        )
    assert record.content == content
    assert record.case_count == 1
    assert store.dataset_versions.get_by_hash(record.content_hash).content == content
    assert [r.feature_name for r in store.dataset_versions.all()] == ["demo"]


def test_load_datasets_from_store_builds_registry_and_skips_empty() -> None:
    store = _store()
    loaded = _loaded()
    with store._db.transaction():
        store.dataset_versions.upsert(
            feature_name="demo",
            version="v1",
            content_hash=loaded.content_hash,
            case_count=loaded.case_count,
            content=loaded.definition.model_dump_json(),
        )
        # Metadata-only row (e.g. a CLI run) must be skipped.
        store.dataset_versions.upsert(
            feature_name="legacy", version="v1", content_hash="hash_no_content"
        )

    registry = load_datasets_from_store(store, model_resolver=_resolver)
    assert registry.features() == ["demo"]
    assert registry.get_latest("demo").case_count == 1
