"""Tests for the dataset-management subsystem (models, loader, validation, registry)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

# Importing features registers email_classifier so the default model resolver works.
import mrds.features  # noqa: F401
from mrds.datasets import (
    DatasetError,
    DatasetNotFoundError,
    DatasetRegistry,
    DatasetValidationError,
    Difficulty,
    LoadedDataset,
    compute_content_hash,
    load_dataset_file,
)
from mrds.datasets.models import DatasetDefinition
from mrds.features.email_classifier import (
    EmailCategory,
    EmailClassificationInput,
    EmailClassificationOutput,
)

REPO_DATASET = Path("datasets/email_classifier/v1.json")
EMAIL_MODELS = {
    "input_model": EmailClassificationInput,
    "output_model": EmailClassificationOutput,
}

VALID_DATASET: dict[str, Any] = {
    "version": "v1",
    "created_at": "2026-01-01",
    "description": "A tiny test dataset.",
    "cases": [
        {
            "id": "t-1",
            "input": {"email_text": "I was charged twice."},
            "expected_output": {"category": "billing", "summary": "Double charge."},
            "expected_difficulty": "easy",
            "notes": "",
        }
    ],
}


def _write(tmp_path: Path, name: str, data: Any, *, feature: str = "email_classifier") -> Path:
    feature_dir = tmp_path / feature
    feature_dir.mkdir(parents=True, exist_ok=True)
    path = feature_dir / name
    path.write_text(json.dumps(data) if not isinstance(data, str) else data, encoding="utf-8")
    return path


# -- loading + models -----------------------------------------------------------


def test_load_repo_dataset() -> None:
    dataset = load_dataset_file(REPO_DATASET, **EMAIL_MODELS)
    assert isinstance(dataset, LoadedDataset)
    assert dataset.feature == "email_classifier"
    assert dataset.version == "v1"
    assert dataset.identity == "email_classifier:v1"
    assert dataset.case_count >= 50
    assert len(dataset.content_hash) == 64


def test_repo_dataset_covers_all_categories_and_edge_difficulties() -> None:
    dataset = load_dataset_file(REPO_DATASET, **EMAIL_MODELS)
    categories = {case.expected_output.category for case in dataset.definition.cases}
    assert categories == set(EmailCategory)
    difficulties = {case.expected_difficulty for case in dataset.definition.cases}
    assert difficulties == set(Difficulty)


def test_cases_are_typed_as_feature_models() -> None:
    dataset = load_dataset_file(REPO_DATASET, **EMAIL_MODELS)
    first = dataset.definition.cases[0]
    assert isinstance(first.input, EmailClassificationInput)
    assert isinstance(first.expected_output, EmailClassificationOutput)


# -- hashing --------------------------------------------------------------------


def test_hash_is_deterministic(tmp_path: Path) -> None:
    path = _write(tmp_path, "v1.json", VALID_DATASET)
    assert (
        load_dataset_file(path, **EMAIL_MODELS).content_hash
        == load_dataset_file(path, **EMAIL_MODELS).content_hash
    )


def test_hash_ignores_created_at_but_tracks_content() -> None:
    parametrised = DatasetDefinition[EmailClassificationInput, EmailClassificationOutput]
    base = parametrised.model_validate(VALID_DATASET)
    other_date = parametrised.model_validate({**VALID_DATASET, "created_at": "2030-12-31"})
    changed = parametrised.model_validate(
        {
            **VALID_DATASET,
            "cases": [{**VALID_DATASET["cases"][0], "notes": "changed content"}],
        }
    )

    assert compute_content_hash(base) == compute_content_hash(other_date)
    assert compute_content_hash(base) != compute_content_hash(changed)


# -- validation of malformed datasets -------------------------------------------


def _mutate(**overrides: Any) -> dict[str, Any]:
    return {**VALID_DATASET, **overrides}


def _case(**overrides: Any) -> dict[str, Any]:
    return [{**VALID_DATASET["cases"][0], **overrides}]


MALFORMED: dict[str, Any] = {
    "not_a_mapping": "[1, 2, 3]",
    "bad_json": "{not valid json",
    "bad_version": _mutate(version="1"),
    "empty_cases": _mutate(cases=[]),
    "missing_description": {k: v for k, v in VALID_DATASET.items() if k != "description"},
    "extra_top_level_key": _mutate(bad="x"),
    "bad_category": _mutate(cases=_case(expected_output={"category": "spam", "summary": "x"})),
    "bad_difficulty": _mutate(cases=_case(expected_difficulty="trivial")),
    "blank_email_text": _mutate(cases=_case(input={"email_text": "   "})),
    "extra_case_key": _mutate(cases=_case(weight=1)),
}


@pytest.mark.parametrize("data", MALFORMED.values(), ids=MALFORMED.keys())
def test_malformed_datasets_raise(tmp_path: Path, data: Any) -> None:
    path = _write(tmp_path, "bad.json", data)
    with pytest.raises(DatasetValidationError):
        load_dataset_file(path, **EMAIL_MODELS)


def test_duplicate_case_ids_raise(tmp_path: Path) -> None:
    dup = _mutate(cases=[VALID_DATASET["cases"][0], VALID_DATASET["cases"][0]])
    path = _write(tmp_path, "dup.json", dup)
    with pytest.raises(DatasetValidationError):
        load_dataset_file(path, **EMAIL_MODELS)


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(DatasetValidationError):
        load_dataset_file(tmp_path / "nope.json", **EMAIL_MODELS)


# -- registry -------------------------------------------------------------------


def test_registry_discovers_repo_dataset() -> None:
    registry = DatasetRegistry.from_directory(Path("datasets"))
    assert "email_classifier" in registry.features()
    assert registry.versions("email_classifier") == ["v1"]
    assert registry.get("email_classifier", "v1").version == "v1"
    assert registry.get_latest("email_classifier").case_count >= 50


def test_registry_latest_picks_highest_version(tmp_path: Path) -> None:
    _write(tmp_path, "v1.json", VALID_DATASET)
    _write(tmp_path, "v2.json", _mutate(version="v2"))
    registry = DatasetRegistry.from_directory(
        tmp_path, model_resolver=lambda _f: (EmailClassificationInput, EmailClassificationOutput)
    )
    assert registry.versions("email_classifier") == ["v1", "v2"]
    assert registry.get_latest("email_classifier").version == "v2"


def test_registry_is_feature_agnostic(tmp_path: Path) -> None:
    """A brand-new feature requires no registry changes — only a model resolver."""

    class QAInput(BaseModel):
        question: str

    class QAOutput(BaseModel):
        answer: str

    data = {
        "version": "v1",
        "created_at": "2026-01-01",
        "description": "rag_qa golden set.",
        "cases": [
            {
                "id": "q-1",
                "input": {"question": "What is MRDS?"},
                "expected_output": {"answer": "An evaluation platform."},
                "expected_difficulty": "easy",
            }
        ],
    }
    _write(tmp_path, "v1.json", data, feature="rag_qa")
    registry = DatasetRegistry.from_directory(
        tmp_path, model_resolver=lambda _f: (QAInput, QAOutput)
    )
    assert registry.features() == ["rag_qa"]
    assert isinstance(registry.get("rag_qa", "v1").definition.cases[0].input, QAInput)


def test_discover_feature_loads_only_that_feature(tmp_path: Path) -> None:
    """With multiple features of *different* schemas in one root, discover_feature loads
    only the named one — and never validates the other against the wrong models."""

    class QAInput(BaseModel):
        question: str

    class QAOutput(BaseModel):
        answer: str

    # email_classifier (input email_text / output category+summary) and a foreign rag_qa
    # feature (input question / output answer) coexist under the same root.
    _write(tmp_path, "v1.json", VALID_DATASET, feature="email_classifier")
    _write(
        tmp_path,
        "v1.json",
        {
            "version": "v1",
            "created_at": "2026-01-01",
            "description": "rag_qa golden set.",
            "cases": [
                {
                    "id": "q-1",
                    "input": {"question": "What is MRDS?"},
                    "expected_output": {"answer": "An evaluation platform."},
                    "expected_difficulty": "easy",
                }
            ],
        },
        feature="rag_qa",
    )

    # A full discover with a single-feature resolver would validate rag_qa's cases against
    # the QA models and email_classifier's against them too — exactly the activation bug.
    with pytest.raises(DatasetValidationError):
        DatasetRegistry.from_directory(tmp_path, model_resolver=lambda _f: (QAInput, QAOutput))

    # Feature-scoped discovery validates *only* rag_qa and ignores the foreign dataset.
    registry = DatasetRegistry(tmp_path, model_resolver=lambda _f: (QAInput, QAOutput))
    assert registry.discover_feature("rag_qa") == 1
    assert registry.features() == ["rag_qa"]
    assert isinstance(registry.get("rag_qa", "v1").definition.cases[0].input, QAInput)


def test_discover_feature_missing_dir_raises(tmp_path: Path) -> None:
    registry = DatasetRegistry(
        tmp_path,
        model_resolver=lambda _f: (EmailClassificationInput, EmailClassificationOutput),
    )
    with pytest.raises(DatasetError, match="No dataset directory for feature 'ghost'"):
        registry.discover_feature("ghost")


def test_registry_unknown_lookups_raise(tmp_path: Path) -> None:
    _write(tmp_path, "v1.json", VALID_DATASET)
    registry = DatasetRegistry.from_directory(
        tmp_path, model_resolver=lambda _f: (EmailClassificationInput, EmailClassificationOutput)
    )
    with pytest.raises(DatasetNotFoundError):
        registry.get("email_classifier", "v9")
    with pytest.raises(DatasetNotFoundError):
        registry.get_latest("nonexistent")


def test_registry_rejects_missing_root(tmp_path: Path) -> None:
    with pytest.raises(DatasetError):
        DatasetRegistry.from_directory(tmp_path / "nope")
