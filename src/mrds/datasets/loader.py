"""Loading and content-hashing of golden dataset files.

The loader owns file I/O and JSON parsing, delegates schema validation to
:mod:`mrds.datasets.validation`, and computes a deterministic, content-based hash.

Hashing rule (mirrors prompts): the hash is taken over the canonicalised
definition **excluding** ``created_at`` (provenance, not content). Editing any
case — input, expected output, difficulty, or notes — changes the hash.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from mrds.core.hashing import hash_json
from mrds.datasets.errors import DatasetValidationError
from mrds.datasets.models import DatasetDefinition, LoadedDataset
from mrds.datasets.validation import validate_dataset_data
from mrds.observability.logging import get_logger

logger = get_logger(__name__)

DEFAULT_DATASETS_DIR = Path("datasets")
DATASET_FILE_SUFFIXES = (".json",)

# Fields excluded from the content hash (provenance, not content).
_HASH_EXCLUDE = {"created_at"}


def compute_content_hash(definition: DatasetDefinition[Any, Any]) -> str:
    """Return a deterministic, content-based hash for a dataset definition."""
    payload = definition.model_dump(mode="json", exclude=_HASH_EXCLUDE)
    return hash_json(payload)


def load_dataset_from_definition_json(
    content: str,
    *,
    input_model: type[BaseModel],
    output_model: type[BaseModel],
    feature: str,
    source_path: Path | None = None,
) -> LoadedDataset:
    """Reconstruct a :class:`LoadedDataset` from a serialized dataset definition.

    The DB read counterpart to :func:`load_dataset_file`: ``content`` is a
    ``DatasetDefinition`` JSON document (as persisted in ``dataset_versions.content``),
    validated against the feature's models exactly like a file would be. The content
    hash is recomputed, matching how filesystem-loaded datasets derive their identity.
    """
    data = json.loads(content)
    definition = validate_dataset_data(
        data, input_model=input_model, output_model=output_model, source=source_path
    )
    return LoadedDataset(
        feature=feature,
        definition=definition,
        content_hash=compute_content_hash(definition),
        source_path=source_path or Path(f"db://{feature}/{definition.version}"),
    )


def load_dataset_file(
    path: Path,
    *,
    input_model: type[BaseModel],
    output_model: type[BaseModel],
    feature: str | None = None,
) -> LoadedDataset:
    """Load, validate, and hash a single dataset file.

    Args:
        path: Path to the dataset JSON file.
        input_model: The feature's input model (cases' ``input`` validated against it).
        output_model: The feature's output model (cases' ``expected_output`` validated against it).
        feature: Feature name; defaults to the parent directory name.

    Raises:
        DatasetValidationError: If the file is missing/unreadable, not valid JSON,
            or fails schema validation.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise DatasetValidationError(f"Cannot read dataset file {path}: {exc}") from exc

    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise DatasetValidationError(f"Malformed JSON in {path}:\n{exc}") from exc

    definition = validate_dataset_data(
        data, input_model=input_model, output_model=output_model, source=path
    )
    resolved_feature = feature or path.parent.name
    content_hash = compute_content_hash(definition)

    logger.debug(
        "Loaded dataset %s:%s (%d cases, hash=%s) from %s",
        resolved_feature,
        definition.version,
        definition.case_count,
        content_hash[:12],
        path,
    )
    return LoadedDataset(
        feature=resolved_feature,
        definition=definition,
        content_hash=content_hash,
        source_path=path,
    )
