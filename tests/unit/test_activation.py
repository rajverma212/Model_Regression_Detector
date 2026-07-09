"""Tests for feature activation: discovering and registering DB-persisted specs."""

from __future__ import annotations

from mrds.activation import register_installed_features
from mrds.core.registry import FeatureRegistry, feature_registry
from mrds.db import EvaluationStore, open_database
from mrds.features.spec import compute_spec_hash
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
            "input": {"text": "the app crashes on launch"},
            "expected_output": {"category": "technical"},
        },
        {
            "id": "c3",
            "input": {"text": "reset my password please"},
            "expected_output": {"category": "account"},
        },
    ]
}


def _persist_spec(store: EvaluationStore, name: str) -> None:
    """Persist a feature spec into the store, as DB-native activation does."""
    spec = infer_feature_spec(_RAW, feature_name=name, feature_type="classification")
    store.feature_specs.upsert(
        feature_name=name,
        content_hash=compute_spec_hash(spec),
        spec_json=spec.model_dump_json(),
        segment_field=spec.segment_field,
    )


def test_store_discovery_registers_persisted_spec() -> None:
    store = EvaluationStore(open_database(":memory:"))
    _persist_spec(store, "from_db")

    registry = FeatureRegistry()
    names = register_installed_features(store=store, registry=registry)
    assert names == ["from_db"]
    assert "from_db" in registry

    # Idempotent: a second pass registers nothing new.
    assert register_installed_features(store=store, registry=registry) == []


def test_discovery_noop_when_no_specs(tmp_path) -> None:
    store = EvaluationStore(open_database(":memory:"))
    registry = FeatureRegistry()
    # No specs on disk and none in the store -> nothing registered.
    assert (
        register_installed_features(specs_dir=tmp_path / "nope", store=store, registry=registry)
        == []
    )
    assert len(registry) == 0


def test_global_registry_only_has_handwritten_features() -> None:
    # No specs/ dir in the repo and no store passed at import -> the global discovery hook
    # registers only the hand-coded built-ins.
    assert feature_registry.names() == ["email_classifier", "ticket_router"]
