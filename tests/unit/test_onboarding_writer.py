"""Tests for the feature-bundle writer."""

from __future__ import annotations

from pathlib import Path

import pytest

from mrds.datasets.registry import DatasetRegistry
from mrds.features.spec import build_input_model, build_output_model, load_feature_spec
from mrds.onboarding import (
    OnboardingError,
    infer_feature_spec,
    scaffold_prompt,
    write_feature_bundle,
)
from mrds.prompts.registry import PromptRegistry

_RAW = {
    "cases": [
        {
            "id": "c1",
            "input": {"text": "refund my charge"},
            "expected_output": {"category": "billing"},
        },
        {
            "id": "c2",
            "input": {"text": "the app crashes"},
            "expected_output": {"category": "technical"},
        },
        {
            "id": "c3",
            "input": {"text": "reset my password"},
            "expected_output": {"category": "account"},
        },
    ]
}


def _spec_and_prompt():
    spec = infer_feature_spec(_RAW, feature_name="support_cls", feature_type="classification")
    return spec, scaffold_prompt(spec, feature_type="classification")


def test_bundle_is_written_and_loadable(tmp_path: Path) -> None:
    spec, prompt = _spec_and_prompt()
    paths = write_feature_bundle(spec, cases=_RAW["cases"], system_prompt=prompt, root=tmp_path)

    assert paths.feature_yaml.exists()
    assert paths.prompt_yaml.exists()
    assert paths.dataset_json.exists()

    # feature.yaml round-trips through the generation layer.
    loaded = load_feature_spec(paths.feature_yaml)
    assert loaded.feature_name == "support_cls"
    assert [f.name for f in loaded.output_fields] == ["category"]

    # Prompt + dataset load through the existing registries.
    prompts = PromptRegistry.from_directory(paths.bundle_dir / "prompts")
    assert prompts.get_latest("support_cls").definition.system_prompt.strip()

    datasets = DatasetRegistry.from_directory(
        paths.bundle_dir / "datasets",
        model_resolver=lambda _f: (build_input_model(loaded), build_output_model(loaded)),
    )
    assert datasets.get_latest("support_cls").definition.case_count == 3


def test_refuses_to_overwrite_existing_bundle(tmp_path: Path) -> None:
    spec, prompt = _spec_and_prompt()
    write_feature_bundle(spec, cases=_RAW["cases"], system_prompt=prompt, root=tmp_path)
    with pytest.raises(OnboardingError, match="already exists"):
        write_feature_bundle(spec, cases=_RAW["cases"], system_prompt=prompt, root=tmp_path)


def test_blank_prompt_rejected(tmp_path: Path) -> None:
    spec, _ = _spec_and_prompt()
    with pytest.raises(OnboardingError, match="must not be blank"):
        write_feature_bundle(spec, cases=_RAW["cases"], system_prompt="   ", root=tmp_path)
    assert not (tmp_path / "support_cls").exists()


def test_case_outside_schema_rejected_and_nothing_written(tmp_path: Path) -> None:
    spec, prompt = _spec_and_prompt()
    bad_cases = [
        {"id": "x", "input": {"text": "hi"}, "expected_output": {"category": "not_a_real_label"}},
    ]
    with pytest.raises(OnboardingError, match="does not match the schema"):
        write_feature_bundle(spec, cases=bad_cases, system_prompt=prompt, root=tmp_path)
    assert not (tmp_path / "support_cls").exists()
