"""Phase 2 — discover installed specs and register them as features.

Scans an installed-specs directory, loads each ``<name>.yaml`` into a ``FeatureSpec``,
and registers a ``GenericStructuredFeature`` (via the existing ``build_from_spec``) in
the feature registry. Additive to the hand-coded ``register_all`` — names already
present (hand-written or previously discovered) are skipped, so it is idempotent and
backward compatible.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from mrds.core.registry import FeatureRegistry, feature_registry
from mrds.prompts.loader import DEFAULT_PROMPTS_DIR

if TYPE_CHECKING:
    from mrds.datasets.registry import DatasetRegistry, ModelResolver
    from mrds.db import EvaluationStore
    from mrds.features.spec import FeatureSpec
    from mrds.prompts.registry import PromptRegistry

#: Default location scanned for installed feature specs (relative to the working dir).
DEFAULT_SPECS_DIR = Path("specs")


def discover_specs(specs_dir: str | Path = DEFAULT_SPECS_DIR) -> list[FeatureSpec]:
    """Load every ``<name>.yaml`` spec from ``specs_dir`` (empty if it doesn't exist)."""
    # Imported lazily: ``mrds.features`` registers installed specs at import time by
    # calling into this module, so importing ``mrds.features.spec`` at module top would
    # create an activation<->features import cycle (and silently skip registration).
    from mrds.features.spec import load_feature_spec

    specs_dir = Path(specs_dir)
    if not specs_dir.is_dir():
        return []
    return [load_feature_spec(path) for path in sorted(specs_dir.glob("*.yaml"))]


def discover_specs_from_store(store: EvaluationStore) -> list[FeatureSpec]:
    """Load every installed spec persisted in the database.

    The DB read counterpart to :func:`discover_specs`. Specs are stored opaquely as
    JSON, so the feature-agnostic store hands back raw rows and this layer (which owns
    the spec model) reconstructs them.
    """
    from mrds.features.spec import FeatureSpec  # lazy: avoid the import cycle (see above)

    return [FeatureSpec.model_validate_json(r.spec_json) for r in store.feature_specs.list_all()]


def load_prompts_from_store(store: EvaluationStore) -> PromptRegistry:
    """Build a :class:`PromptRegistry` from prompt versions persisted in the database.

    The DB counterpart to :meth:`PromptRegistry.from_directory`. Rows without persisted
    content (written before prompts moved into the DB, or by paths that only recorded
    metadata) are skipped — their body still lives on the filesystem.
    """
    from mrds.prompts.loader import load_prompt_from_definition_json
    from mrds.prompts.registry import PromptRegistry

    registry = PromptRegistry()
    for rec in store.prompt_versions.all():
        if not rec.content:
            continue
        registry.register(
            load_prompt_from_definition_json(
                rec.content,
                feature=rec.feature_name,
                source_path=Path(rec.path) if rec.path else None,
            )
        )
    return registry


def load_datasets_from_store(
    store: EvaluationStore,
    *,
    model_resolver: ModelResolver | None = None,
    feature: str | None = None,
) -> DatasetRegistry:
    """Build a :class:`DatasetRegistry` from dataset versions persisted in the database.

    The DB counterpart to :meth:`DatasetRegistry.from_directory`. Cases are validated
    against the feature's models (resolved via ``model_resolver``, defaulting to the
    global feature registry), so the relevant features must be registered first. Rows
    without persisted content are skipped — their cases still live on the filesystem.

    ``feature`` scopes loading to one feature's rows. **Required** whenever the resolver
    only knows a single feature's models (e.g. first-evaluation activation): without it,
    every other feature's persisted dataset would be validated against the wrong schema —
    the store-side twin of the shared-directory discovery bug.
    """
    from mrds.datasets.loader import load_dataset_from_definition_json
    from mrds.datasets.registry import DatasetRegistry, _default_model_resolver

    resolve = model_resolver or _default_model_resolver
    registry = DatasetRegistry(model_resolver=resolve)
    for rec in store.dataset_versions.all():
        if not rec.content or (feature is not None and rec.feature_name != feature):
            continue
        input_model, output_model = resolve(rec.feature_name)
        registry.register(
            load_dataset_from_definition_json(
                rec.content,
                input_model=input_model,
                output_model=output_model,
                feature=rec.feature_name,
                source_path=Path(rec.path) if rec.path else None,
            )
        )
    return registry


def register_installed_features(
    *,
    specs_dir: str | Path = DEFAULT_SPECS_DIR,
    prompts_dir: str | Path = DEFAULT_PROMPTS_DIR,
    registry: FeatureRegistry = feature_registry,
    store: EvaluationStore | None = None,
) -> list[str]:
    """Register all discovered spec features not already in ``registry``.

    Specs are sourced from ``specs_dir`` (filesystem) and, when ``store`` is given,
    also from the database — the union, so a feature persisted in either place is
    registered. Returns the names newly registered. Idempotent; never clobbers an
    existing (hand-coded or previously registered) feature.
    """
    from mrds.features.spec import build_from_spec  # lazy: avoid the import cycle (see above)

    specs = list(discover_specs(specs_dir))
    if store is not None:
        specs.extend(discover_specs_from_store(store))

    registered: list[str] = []
    for spec in specs:
        if spec.feature_name in registry:
            continue
        feature = build_from_spec(spec, prompts_dir=Path(prompts_dir))
        registry.register(feature)
        registered.append(spec.feature_name)
    return registered
