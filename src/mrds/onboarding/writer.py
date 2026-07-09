"""Build validated in-memory feature-bundle definitions for DB-native activation.

Turns a validated ``FeatureSpec`` + labeled cases + system prompt into ``PromptDefinition``
and ``DatasetDefinition`` objects — the same content the platform persists into the
database (the system of record). No file I/O: the database, not the filesystem, holds
feature bundles.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

from pydantic import ValidationError

from mrds.datasets.models import DatasetDefinition
from mrds.datasets.validation import validate_dataset_data
from mrds.features.spec import FeatureSpec, build_input_model, build_output_model
from mrds.onboarding.errors import OnboardingError
from mrds.prompts.models import PromptDefinition

_DEFAULT_DIFFICULTY = "medium"


def _validate_cases(spec: FeatureSpec, cases: Sequence[dict]) -> None:
    """LLM-free consistency gate: every case must validate against the generated models."""
    input_model = build_input_model(spec)
    output_model = build_output_model(spec)
    for case in cases:
        case_id = case.get("id", "?")
        try:
            input_model.model_validate(case["input"])
            output_model.model_validate(case["expected_output"])
        except ValidationError as exc:
            raise OnboardingError(f"case '{case_id}' does not match the schema: {exc}") from exc


def _prompt_dict(spec: FeatureSpec, system_prompt: str) -> dict:
    return {
        "version": "v1",
        "created_at": date.today().isoformat(),
        "description": spec.title or f"Prompt for {spec.feature_name}.",
        "tags": [spec.feature_name],
        "system_prompt": system_prompt,
        "few_shot_examples": [],
    }


def _dataset_dict(spec: FeatureSpec, cases: Sequence[dict]) -> dict:
    return {
        "version": "v1",
        "created_at": date.today().isoformat(),
        "description": spec.title or f"Golden dataset for {spec.feature_name}.",
        "cases": [
            {
                "id": case["id"],
                "input": case["input"],
                "expected_output": case["expected_output"],
                "expected_difficulty": case.get("expected_difficulty", _DEFAULT_DIFFICULTY),
                "notes": case.get("notes", ""),
            }
            for case in cases
        ],
    }


def build_prompt_definition(spec: FeatureSpec, system_prompt: str) -> PromptDefinition:
    """Build and validate the v1 prompt definition for a feature — no file I/O.

    Persisted straight into the database as the prompt content (DB-native activation).
    """
    if not system_prompt.strip():
        raise OnboardingError("system_prompt must not be blank")
    return PromptDefinition.model_validate(_prompt_dict(spec, system_prompt))


def build_dataset_definition(
    spec: FeatureSpec, cases: Sequence[dict]
) -> DatasetDefinition[Any, Any]:
    """Build and validate the v1 dataset definition for a feature — no file I/O.

    Cases are validated against the feature's generated models, exactly as the dataset
    file would be on load. Persisted straight into the database as the dataset content.
    """
    _validate_cases(spec, cases)
    return validate_dataset_data(
        _dataset_dict(spec, cases),
        input_model=build_input_model(spec),
        output_model=build_output_model(spec),
    )
