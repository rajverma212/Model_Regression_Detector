"""The feature registry — the backbone of the platform's extensibility.

Features register themselves into a process-wide :data:`feature_registry`. The
evaluation engine, CLI, etc. look features up by name and never import a concrete
feature directly. Importing :mod:`mrds.features` populates the registry.
"""

from __future__ import annotations

from mrds.core.errors import FeatureError, FeatureNotFoundError
from mrds.core.interfaces import Feature
from mrds.observability.logging import get_logger

logger = get_logger(__name__)


class FeatureRegistry:
    """A name-keyed registry of :class:`Feature` instances."""

    def __init__(self) -> None:
        self._features: dict[str, Feature] = {}

    def register(self, feature: Feature) -> None:
        """Register a feature instance.

        Raises:
            FeatureError: If ``feature`` is not a :class:`Feature`, has no name, or
                a feature with the same name is already registered.
        """
        if not isinstance(feature, Feature):
            raise FeatureError(f"{feature!r} is not a Feature instance")
        name = getattr(type(feature), "name", None)
        if not name:
            raise FeatureError(f"{type(feature).__name__} does not declare a 'name'")
        if name in self._features:
            raise FeatureError(f"Feature '{name}' is already registered")
        self._features[name] = feature
        logger.info("Registered feature '%s'", name)

    def get(self, name: str) -> Feature:
        """Return the feature registered under ``name``."""
        try:
            return self._features[name]
        except KeyError:
            raise FeatureNotFoundError(f"No feature registered as '{name}'") from None

    def names(self) -> list[str]:
        """Return all registered feature names, sorted."""
        return sorted(self._features)

    def all(self) -> list[Feature]:
        """Return all registered features, ordered by name."""
        return [self._features[n] for n in self.names()]

    def __contains__(self, name: object) -> bool:
        return name in self._features

    def __len__(self) -> int:
        return len(self._features)


#: Process-wide registry populated by importing :mod:`mrds.features`.
feature_registry = FeatureRegistry()


def get_feature(name: str) -> Feature:
    """Convenience accessor for :data:`feature_registry`."""
    return feature_registry.get(name)
