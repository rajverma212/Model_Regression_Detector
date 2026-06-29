"""Unit tests for persisting prompt versions (their content) in the database (Phase 3).

Cover the new ``prompt_versions.content`` column: the repository stores/reads content,
a prompt definition round-trips through the DB, and a PromptRegistry can be rebuilt from
the database (skipping rows whose content was never persisted).
"""

from __future__ import annotations

from datetime import date

from mrds.activation.discovery import load_prompts_from_store
from mrds.db import EvaluationStore, open_database
from mrds.prompts.loader import compute_content_hash, load_prompt_from_definition_json
from mrds.prompts.models import PromptDefinition


def _definition(
    version: str = "v1", system_prompt: str = "You are a classifier."
) -> PromptDefinition:
    return PromptDefinition(
        version=version,
        created_at=date(2026, 1, 1),
        description="Test prompt.",
        system_prompt=system_prompt,
    )


def _store() -> EvaluationStore:
    return EvaluationStore(open_database(":memory:"))


def test_repository_upsert_persists_content() -> None:
    store = _store()
    definition = _definition()
    content = definition.model_dump_json()
    with store._db.transaction():
        record = store.prompt_versions.upsert(
            feature_name="demo",
            version="v1",
            content_hash=compute_content_hash(definition),
            content=content,
        )
    assert record.content == content
    assert store.prompt_versions.get_by_hash(record.content_hash).content == content
    assert [r.feature_name for r in store.prompt_versions.all()] == ["demo"]


def test_load_prompt_from_definition_json_roundtrips() -> None:
    definition = _definition()
    loaded = load_prompt_from_definition_json(definition.model_dump_json(), feature="demo")
    assert loaded.feature == "demo"
    assert loaded.definition == definition
    assert loaded.content_hash == compute_content_hash(definition)
    assert str(loaded.source_path) == "db:/demo/v1"  # synthetic provenance for DB prompts


def test_load_prompts_from_store_builds_registry_and_skips_empty() -> None:
    store = _store()
    definition = _definition()
    with store._db.transaction():
        # A prompt with persisted content (Phase 3 activation path) ...
        store.prompt_versions.upsert(
            feature_name="demo",
            version="v1",
            content_hash=compute_content_hash(definition),
            content=definition.model_dump_json(),
        )
        # ... and a metadata-only row (e.g. a CLI run) that must be skipped.
        store.prompt_versions.upsert(
            feature_name="legacy", version="v1", content_hash="hash_no_content"
        )

    registry = load_prompts_from_store(store)
    assert registry.features() == ["demo"]
    assert registry.get_latest("demo").definition == definition
