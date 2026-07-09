"""Phase 6 — make the database the runtime source of truth for feature bundles.

Two startup helpers the live runtimes call once, after opening the store:

* :func:`ensure_builtin_bundles` — seed the committed prompt/dataset **content** of the
  hand-coded built-in features (``email_classifier``, ``ticket_router``) into the database.
  Their bundles live as committed ``prompts/<f>`` / ``datasets/<f>`` files, but the engine
  now reads bundle content from the DB, so that content must exist there. Idempotent: the
  content-hash upsert backfills only rows that lack content.
* :func:`bootstrap_platform` — register every feature (built-in + DB-activated) and ensure
  the built-in bundle content is present, so ``load_prompts_from_store`` /
  ``load_datasets_from_store`` can resolve them all.

The committed ``prompts/`` / ``datasets/`` directories are now only the **seed source** for
the database, not a runtime resolution path.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from mrds.activation.discovery import register_installed_features
from mrds.core.registry import FeatureRegistry, feature_registry
from mrds.datasets.errors import DatasetNotFoundError
from mrds.datasets.loader import DEFAULT_DATASETS_DIR
from mrds.prompts.errors import PromptNotFoundError
from mrds.prompts.loader import DEFAULT_PROMPTS_DIR

if TYPE_CHECKING:
    from mrds.db import EvaluationStore


def ensure_builtin_bundles(
    store: EvaluationStore,
    *,
    prompts_dir: str | Path = DEFAULT_PROMPTS_DIR,
    datasets_dir: str | Path = DEFAULT_DATASETS_DIR,
    registry: FeatureRegistry = feature_registry,
) -> list[str]:
    """Seed committed built-in prompt/dataset content into the store (idempotent).

    Reads the on-disk bundle for every registered feature that still has committed files
    (the hand-coded built-ins) and persists its prompt/dataset content into the DB. Spec
    (onboarded) features are skipped — they have no committed files and were already
    persisted at activation. Returns the feature names whose content was seeded.
    """
    from mrds.datasets.registry import DatasetRegistry
    from mrds.prompts.registry import PromptRegistry

    prompts_dir, datasets_dir = Path(prompts_dir), Path(datasets_dir)
    if not prompts_dir.is_dir() or not datasets_dir.is_dir():
        return []

    prompts = PromptRegistry.from_directory(prompts_dir)
    datasets = DatasetRegistry.from_directory(datasets_dir)  # default resolver = global registry

    seeded: list[str] = []
    for name in registry.names():
        try:
            prompt = prompts.get_latest(name)
            dataset = datasets.get_latest(name)
        except (PromptNotFoundError, DatasetNotFoundError):
            continue  # spec/onboarded feature: no committed bundle to seed
        store.prompt_versions.upsert(
            feature_name=name,
            version=prompt.version,
            content_hash=prompt.content_hash,
            path=str(prompt.source_path),
            content=prompt.definition.model_dump_json(),
        )
        store.dataset_versions.upsert(
            feature_name=name,
            version=dataset.version,
            content_hash=dataset.content_hash,
            case_count=dataset.case_count,
            path=str(dataset.source_path),
            content=dataset.definition.model_dump_json(),
        )
        seeded.append(name)
    return seeded


def bootstrap_platform(
    store: EvaluationStore, *, registry: FeatureRegistry = feature_registry
) -> None:
    """Prepare the runtime: register all features and seed built-in bundle content.

    After this, every feature (built-in + DB-activated) is registered and its prompt/dataset
    content is in the store, so the engine can be built from ``load_prompts_from_store`` /
    ``load_datasets_from_store`` with no filesystem resolution.
    """
    import mrds.features  # noqa: F401 - importing registers the built-in features

    register_installed_features(store=store, registry=registry)
    ensure_builtin_bundles(store, registry=registry)
