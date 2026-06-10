"""Phase 2 — discover installed specs and register them as features.

Scans an installed-specs directory, loads each ``<name>.yaml`` into a ``FeatureSpec``,
and registers a ``GenericStructuredFeature`` (via the existing ``build_from_spec``) in
the feature registry. Additive to the hand-coded ``register_all`` — names already
present (hand-written or previously discovered) are skipped, so it is idempotent and
backward compatible.
"""

from __future__ import annotations

from pathlib import Path

from mrds.core.registry import FeatureRegistry, feature_registry
from mrds.features.spec import FeatureSpec, build_from_spec, load_feature_spec
from mrds.prompts.loader import DEFAULT_PROMPTS_DIR

#: Default location scanned for installed feature specs (relative to the working dir).
DEFAULT_SPECS_DIR = Path("specs")


def discover_specs(specs_dir: str | Path = DEFAULT_SPECS_DIR) -> list[FeatureSpec]:
    """Load every ``<name>.yaml`` spec from ``specs_dir`` (empty if it doesn't exist)."""
    specs_dir = Path(specs_dir)
    if not specs_dir.is_dir():
        return []
    return [load_feature_spec(path) for path in sorted(specs_dir.glob("*.yaml"))]


def register_installed_features(
    *,
    specs_dir: str | Path = DEFAULT_SPECS_DIR,
    prompts_dir: str | Path = DEFAULT_PROMPTS_DIR,
    registry: FeatureRegistry = feature_registry,
) -> list[str]:
    """Register all discovered spec features not already in ``registry``.

    Returns the names newly registered. Idempotent; never clobbers an existing
    (hand-coded or previously registered) feature.
    """
    registered: list[str] = []
    for spec in discover_specs(specs_dir):
        if spec.feature_name in registry:
            continue
        feature = build_from_spec(spec, prompts_dir=Path(prompts_dir))
        registry.register(feature)
        registered.append(spec.feature_name)
    return registered
