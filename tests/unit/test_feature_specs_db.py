"""Unit tests for persisting feature specifications in the database (Phase 2).

Cover the new ``feature_specs`` storage end to end: the opaque repository CRUD, the
spec content hash, a full FeatureSpec round-trip through the DB, and DB-backed
discovery/registration.
"""

from __future__ import annotations

from mrds.activation.discovery import discover_specs_from_store, register_installed_features
from mrds.core.registry import FeatureRegistry
from mrds.db import EvaluationStore, open_database
from mrds.features.spec import (
    FeatureSpec,
    FieldSpec,
    FieldType,
    ScorerKind,
    ScorerSpec,
    compute_spec_hash,
)


def _spec(name: str = "demo_cls", *, values: list[str] | None = None) -> FeatureSpec:
    return FeatureSpec(
        feature_name=name,
        input_fields=[FieldSpec(name="text")],
        output_fields=[
            FieldSpec(name="category", type=FieldType.ENUM, values=values or ["a", "b"])
        ],
        scoring=[ScorerSpec(field="category", scorer=ScorerKind.EXACT_MATCH)],
        segment_field="category",
    )


def _store() -> EvaluationStore:
    return EvaluationStore(open_database(":memory:"))


def test_compute_spec_hash_is_deterministic_and_content_sensitive() -> None:
    spec = _spec()
    assert compute_spec_hash(spec) == compute_spec_hash(_spec())  # same content, same hash
    assert compute_spec_hash(spec) != compute_spec_hash(_spec(values=["a", "b", "c"]))


def test_repository_upsert_get_list_roundtrip() -> None:
    store = _store()
    spec = _spec()
    record = store.feature_specs.upsert(
        feature_name=spec.feature_name,
        content_hash=compute_spec_hash(spec),
        spec_json=spec.model_dump_json(),
        segment_field=spec.segment_field,
    )
    assert record.feature_name == "demo_cls"
    assert record.segment_field == "category"
    assert store.feature_specs.get("demo_cls") == record
    assert store.feature_specs.get("missing") is None
    assert [r.feature_name for r in store.feature_specs.list_all()] == ["demo_cls"]


def test_upsert_updates_in_place_and_preserves_created_at() -> None:
    store = _store()
    first = store.feature_specs.upsert(
        feature_name="demo_cls",
        content_hash="hash_a",
        spec_json='{"v": 1}',
        created_at="2026-01-01T00:00:00+00:00",
    )
    second = store.feature_specs.upsert(
        feature_name="demo_cls",
        content_hash="hash_b",
        spec_json='{"v": 2}',
    )
    assert second.id == first.id  # same row, updated in place
    assert second.content_hash == "hash_b"
    assert second.spec_json == '{"v": 2}'
    assert second.created_at == first.created_at  # preserved
    assert second.updated_at != first.created_at  # advanced
    assert len(store.feature_specs.list_all()) == 1


def test_feature_spec_roundtrips_through_the_database() -> None:
    store = _store()
    original = _spec()
    store.feature_specs.upsert(
        feature_name=original.feature_name,
        content_hash=compute_spec_hash(original),
        spec_json=original.model_dump_json(),
        segment_field=original.segment_field,
    )
    [reconstructed] = discover_specs_from_store(store)
    assert reconstructed == original


def test_register_installed_features_registers_db_specs() -> None:
    store = _store()
    spec = _spec(name="db_only_feature")
    store.feature_specs.upsert(
        feature_name=spec.feature_name,
        content_hash=compute_spec_hash(spec),
        spec_json=spec.model_dump_json(),
        segment_field=spec.segment_field,
    )
    registry = FeatureRegistry()
    # No specs_dir on disk; the feature is discovered purely from the store.
    registered = register_installed_features(
        specs_dir="/nonexistent", registry=registry, store=store
    )
    assert registered == ["db_only_feature"]
    assert "db_only_feature" in registry


def test_register_without_store_ignores_the_database() -> None:
    """Default behaviour is unchanged: no store means filesystem-only discovery."""
    store = _store()
    spec = _spec(name="db_only_feature")
    store.feature_specs.upsert(
        feature_name=spec.feature_name,
        content_hash=compute_spec_hash(spec),
        spec_json=spec.model_dump_json(),
    )
    registry = FeatureRegistry()
    registered = register_installed_features(specs_dir="/nonexistent", registry=registry)
    assert registered == []
