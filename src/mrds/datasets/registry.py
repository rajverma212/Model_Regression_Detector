"""Feature-agnostic registry that discovers and resolves versioned datasets.

Mirrors :class:`mrds.prompts.registry.PromptRegistry`. It scans
``<root>/<feature>/<version>.json`` and indexes datasets by
``feature -> version -> LoadedDataset``.

To validate a dataset it needs the feature's input/output models. These are
obtained via a *model resolver* — by default the global feature registry, so any
feature that registers itself (Sprint 3 pattern) becomes loadable with **no
changes here**. A custom resolver can be injected (used in tests and to decouple).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from mrds.core.errors import FeatureError
from mrds.core.registry import feature_registry
from mrds.datasets.errors import DatasetError, DatasetNotFoundError
from mrds.datasets.loader import (
    DATASET_FILE_SUFFIXES,
    DEFAULT_DATASETS_DIR,
    load_dataset_file,
)
from mrds.datasets.models import LoadedDataset
from mrds.observability.logging import get_logger

logger = get_logger(__name__)

#: Resolves a feature name to its ``(input_model, output_model)``.
ModelResolver = Callable[[str], tuple[type[BaseModel], type[BaseModel]]]


def _default_model_resolver(feature: str) -> tuple[type[BaseModel], type[BaseModel]]:
    """Resolve a feature's I/O models via the global feature registry."""
    try:
        instance = feature_registry.get(feature)
    except FeatureError as exc:
        raise DatasetError(f"Cannot resolve models for dataset feature '{feature}': {exc}") from exc
    return instance.input_model, instance.output_model


class DatasetRegistry:
    """Indexes datasets by feature and version, with discovery from disk."""

    def __init__(
        self,
        root: Path = DEFAULT_DATASETS_DIR,
        *,
        model_resolver: ModelResolver = _default_model_resolver,
    ) -> None:
        self._root = root
        self._resolve_models = model_resolver
        self._datasets: dict[str, dict[str, LoadedDataset]] = {}

    # -- construction -----------------------------------------------------------

    @classmethod
    def from_directory(
        cls,
        root: Path = DEFAULT_DATASETS_DIR,
        *,
        model_resolver: ModelResolver = _default_model_resolver,
    ) -> DatasetRegistry:
        """Build a registry and eagerly discover all datasets under ``root``."""
        registry = cls(root, model_resolver=model_resolver)
        registry.discover()
        return registry

    def discover(self) -> int:
        """Scan the root directory and register every dataset file found.

        Returns:
            The number of datasets registered.

        Raises:
            DatasetError: If the root directory does not exist.
        """
        if not self._root.is_dir():
            raise DatasetError(f"Datasets root does not exist: {self._root}")

        count = 0
        for feature_dir in sorted(p for p in self._root.iterdir() if p.is_dir()):
            input_model, output_model = self._resolve_models(feature_dir.name)
            for dataset_file in sorted(self._iter_dataset_files(feature_dir)):
                dataset = load_dataset_file(
                    dataset_file,
                    input_model=input_model,
                    output_model=output_model,
                    feature=feature_dir.name,
                )
                self.register(dataset)
                count += 1

        logger.info(
            "Discovered %d dataset(s) across %d feature(s) under %s",
            count,
            len(self._datasets),
            self._root,
        )
        return count

    def discover_feature(self, feature: str) -> int:
        """Scan and register only the datasets under ``<root>/<feature>/``.

        A feature-scoped counterpart to :meth:`discover`: it resolves models and
        validates files for **one** feature, leaving other features' datasets in the
        shared root untouched. Use it when the resolver only knows one feature's models
        (e.g. first-evaluation onboarding), where a full ``discover`` would validate
        every other feature's dataset against the wrong schema.

        Returns:
            The number of datasets registered for ``feature``.

        Raises:
            DatasetError: If the feature's dataset directory does not exist.
        """
        feature_dir = self._root / feature
        if not feature_dir.is_dir():
            raise DatasetError(f"No dataset directory for feature '{feature}' under {self._root}")

        input_model, output_model = self._resolve_models(feature)
        count = 0
        for dataset_file in sorted(self._iter_dataset_files(feature_dir)):
            dataset = load_dataset_file(
                dataset_file,
                input_model=input_model,
                output_model=output_model,
                feature=feature,
            )
            self.register(dataset)
            count += 1

        logger.info("Discovered %d dataset(s) for feature %s under %s", count, feature, self._root)
        return count

    def register(self, dataset: LoadedDataset) -> None:
        """Register a single loaded dataset.

        Raises:
            DatasetError: If the same feature/version is registered twice.
        """
        versions = self._datasets.setdefault(dataset.feature, {})
        if dataset.version in versions:
            raise DatasetError(
                f"Duplicate dataset version for {dataset.identity} "
                f"({versions[dataset.version].source_path} and {dataset.source_path})"
            )
        versions[dataset.version] = dataset

    # -- lookup -----------------------------------------------------------------

    def get(self, feature: str, version: str) -> LoadedDataset:
        """Return the dataset for an exact ``feature`` and ``version``."""
        try:
            return self._datasets[feature][version]
        except KeyError:
            raise DatasetNotFoundError(f"No dataset registered for {feature}:{version}") from None

    def get_latest(self, feature: str) -> LoadedDataset:
        """Return the highest-numbered version for ``feature``."""
        versions = self._datasets.get(feature)
        if not versions:
            raise DatasetNotFoundError(f"No datasets registered for feature '{feature}'")
        return max(versions.values(), key=lambda d: d.definition.version_number)

    def versions(self, feature: str) -> list[str]:
        """Return the registered version labels for ``feature``, lowest first."""
        versions = self._datasets.get(feature, {})
        return sorted(versions, key=lambda v: versions[v].definition.version_number)

    def features(self) -> list[str]:
        """Return all registered feature names, sorted."""
        return sorted(self._datasets)

    def __len__(self) -> int:
        return sum(len(v) for v in self._datasets.values())

    # -- helpers ----------------------------------------------------------------

    @staticmethod
    def _iter_dataset_files(feature_dir: Path) -> list[Path]:
        return [
            p for p in feature_dir.iterdir() if p.is_file() and p.suffix in DATASET_FILE_SUFFIXES
        ]
