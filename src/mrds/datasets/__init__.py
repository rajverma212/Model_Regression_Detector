"""Golden dataset management: human-labeled evaluation sets as versioned artifacts.

Mirrors the prompt subsystem, with responsibilities split across modules:

- :mod:`mrds.datasets.models` — generic Pydantic dataset/case models.
- :mod:`mrds.datasets.validation` — validate raw data against a feature's I/O models.
- :mod:`mrds.datasets.loader` — file I/O, JSON parsing, content hashing.
- :mod:`mrds.datasets.registry` — feature-agnostic discovery and version resolution.
- :mod:`mrds.datasets.errors` — the dataset error hierarchy.
"""

from mrds.datasets.errors import (
    DatasetError,
    DatasetNotFoundError,
    DatasetValidationError,
)
from mrds.datasets.loader import (
    DEFAULT_DATASETS_DIR,
    compute_content_hash,
    load_dataset_file,
    load_dataset_from_definition_json,
)
from mrds.datasets.models import (
    DatasetCase,
    DatasetDefinition,
    Difficulty,
    LoadedDataset,
)
from mrds.datasets.registry import DatasetRegistry

__all__ = [
    "DEFAULT_DATASETS_DIR",
    "DatasetCase",
    "DatasetDefinition",
    "DatasetError",
    "DatasetNotFoundError",
    "DatasetRegistry",
    "DatasetValidationError",
    "Difficulty",
    "LoadedDataset",
    "compute_content_hash",
    "load_dataset_file",
    "load_dataset_from_definition_json",
]
