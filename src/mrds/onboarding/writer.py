"""Write a validated, isolated feature bundle to disk.

Produces the Phase-2 bundle layout under ``<root>/<feature_name>/``::

    feature.yaml
    prompts/<feature_name>/v1.yaml
    datasets/<feature_name>/v1.json

so the result is immediately loadable by ``load_feature_spec`` + the prompt/dataset
registries. Writing is isolated (never the shared ``prompts/`` / ``datasets/`` roots)
and atomic (temp dir + rename); an existing bundle is never overwritten.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import yaml
from pydantic import ValidationError

from mrds.features.spec import FeatureSpec, build_input_model, build_output_model
from mrds.onboarding.errors import OnboardingError

_DEFAULT_DIFFICULTY = "medium"


@dataclass(frozen=True)
class BundlePaths:
    """Resolved paths of a written feature bundle."""

    bundle_dir: Path
    feature_yaml: Path
    prompt_yaml: Path
    dataset_json: Path


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


def _feature_yaml(spec: FeatureSpec) -> str:
    return yaml.safe_dump(spec.model_dump(mode="json"), sort_keys=False)


def _prompt_yaml(spec: FeatureSpec, system_prompt: str) -> str:
    data = {
        "version": "v1",
        "created_at": date.today().isoformat(),
        "description": spec.title or f"Prompt for {spec.feature_name}.",
        "tags": [spec.feature_name],
        "system_prompt": system_prompt,
        "few_shot_examples": [],
    }
    return yaml.safe_dump(data, sort_keys=False)


def _dataset_json(spec: FeatureSpec, cases: Sequence[dict]) -> str:
    data = {
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
    return json.dumps(data, indent=2)


def write_feature_bundle(
    spec: FeatureSpec,
    *,
    cases: Sequence[dict],
    system_prompt: str,
    root: str | Path,
) -> BundlePaths:
    """Validate inputs and atomically write an isolated feature bundle.

    Raises :class:`OnboardingError` on a blank prompt, a case that does not match the
    schema, or an already-existing bundle.
    """
    if not system_prompt.strip():
        raise OnboardingError("system_prompt must not be blank")
    _validate_cases(spec, cases)

    root = Path(root)
    bundle = root / spec.feature_name
    if bundle.exists():
        raise OnboardingError(f"feature bundle already exists: {bundle}")
    root.mkdir(parents=True, exist_ok=True)

    staging = Path(tempfile.mkdtemp(prefix=f".{spec.feature_name}_", dir=root))
    try:
        (staging / "feature.yaml").write_text(_feature_yaml(spec), encoding="utf-8")

        prompt_dir = staging / "prompts" / spec.feature_name
        prompt_dir.mkdir(parents=True)
        (prompt_dir / "v1.yaml").write_text(_prompt_yaml(spec, system_prompt), encoding="utf-8")

        dataset_dir = staging / "datasets" / spec.feature_name
        dataset_dir.mkdir(parents=True)
        (dataset_dir / "v1.json").write_text(_dataset_json(spec, cases), encoding="utf-8")

        os.replace(staging, bundle)  # atomic rename within the same directory/filesystem
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return BundlePaths(
        bundle_dir=bundle,
        feature_yaml=bundle / "feature.yaml",
        prompt_yaml=bundle / "prompts" / spec.feature_name / "v1.yaml",
        dataset_json=bundle / "datasets" / spec.feature_name / "v1.json",
    )
