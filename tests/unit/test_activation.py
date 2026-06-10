"""Tests for the feature-activation flow (install + discovery + end-to-end)."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

import pytest

from mrds.activation import (
    ActivationError,
    install_bundle,
    register_installed_features,
)
from mrds.core.registry import FeatureRegistry, feature_registry
from mrds.dashboard.data import DashboardData
from mrds.datasets.registry import DatasetRegistry
from mrds.db import EvaluationStore, open_database
from mrds.evaluation import EvaluationConfig, EvaluationEngine
from mrds.features.spec import build_from_spec, load_feature_spec
from mrds.llm.base import LLMMessage, LLMResult
from mrds.onboarding import infer_feature_spec, scaffold_prompt, write_feature_bundle
from mrds.prompts.registry import PromptRegistry

_RAW = {
    "cases": [
        {
            "id": "c1",
            "input": {"text": "please refund my charge"},
            "expected_output": {"category": "billing"},
        },
        {
            "id": "c2",
            "input": {"text": "send me an invoice"},
            "expected_output": {"category": "billing"},
        },
        {
            "id": "c3",
            "input": {"text": "the app crashes on launch"},
            "expected_output": {"category": "technical"},
        },
        {
            "id": "c4",
            "input": {"text": "reset my password please"},
            "expected_output": {"category": "account"},
        },
    ]
}
_ORACLE = {c["input"]["text"]: c["expected_output"]["category"] for c in _RAW["cases"]}
_ORDER = ["account", "billing", "technical"]


class _Stub:
    def __init__(self, wrong: frozenset[str] = frozenset()) -> None:
        self._wrong = wrong

    def parse_structured(
        self, *, model: str, messages: Sequence[LLMMessage], schema: type
    ) -> LLMResult:
        text = messages[-1].content
        label = _ORACLE.get(text, "billing")
        if text in self._wrong:
            label = _ORDER[(_ORDER.index(label) + 1) % len(_ORDER)]
        return LLMResult(
            parsed=schema.model_validate({"category": label}),
            model=model,
            input_tokens=5,
            output_tokens=2,
            total_tokens=7,
        )


def _onboard_bundle(tmp_path: Path, name: str = "support_cls") -> Path:
    """Run the onboarding core to produce a bundle; return its directory."""
    spec = infer_feature_spec(_RAW, feature_name=name, feature_type="classification")
    prompt = scaffold_prompt(spec, feature_type="classification")
    paths = write_feature_bundle(
        spec, cases=_RAW["cases"], system_prompt=prompt, root=tmp_path / "work"
    )
    return paths.bundle_dir


# -- Phase 1: install -----------------------------------------------------------


def test_install_copies_artifacts_to_discoverable_locations(tmp_path: Path) -> None:
    bundle = _onboard_bundle(tmp_path)
    root = tmp_path / "platform"
    installed = install_bundle(bundle, root=root)

    assert installed.spec == root / "specs" / "support_cls.yaml"
    assert installed.prompt == root / "prompts" / "support_cls" / "v1.yaml"
    assert installed.dataset == root / "datasets" / "support_cls" / "v1.json"
    assert all(p.exists() for p in (installed.spec, installed.prompt, installed.dataset))
    assert load_feature_spec(installed.spec).feature_name == "support_cls"


def test_install_refuses_to_overwrite(tmp_path: Path) -> None:
    bundle = _onboard_bundle(tmp_path)
    root = tmp_path / "platform"
    install_bundle(bundle, root=root)
    with pytest.raises(ActivationError, match="already installed"):
        install_bundle(bundle, root=root)


def test_install_rejects_invalid_bundle(tmp_path: Path) -> None:
    bundle = _onboard_bundle(tmp_path)
    # Corrupt the dataset with a label outside the declared enum.
    dataset = bundle / "datasets" / "support_cls" / "v1.json"
    dataset.write_text(
        '{"version":"v1","created_at":"2026-06-10","description":"x","cases":['
        '{"id":"c1","input":{"text":"hi"},"expected_output":{"category":"nope"},'
        '"expected_difficulty":"easy","notes":""}]}',
        encoding="utf-8",
    )
    with pytest.raises(ActivationError, match="does not match the spec"):
        install_bundle(bundle, root=tmp_path / "platform")
    assert not (tmp_path / "platform" / "specs").exists()


# -- Phase 2: discovery / registration ------------------------------------------


def test_discovery_registers_installed_feature(tmp_path: Path) -> None:
    bundle = _onboard_bundle(tmp_path)
    root = tmp_path / "platform"
    install_bundle(bundle, root=root)

    registry = FeatureRegistry()
    names = register_installed_features(
        specs_dir=root / "specs", prompts_dir=root / "prompts", registry=registry
    )
    assert names == ["support_cls"]
    assert "support_cls" in registry
    # Idempotent: a second pass registers nothing new.
    assert (
        register_installed_features(
            specs_dir=root / "specs", prompts_dir=root / "prompts", registry=registry
        )
        == []
    )


def test_discovery_noop_when_specs_dir_absent(tmp_path: Path) -> None:
    registry = FeatureRegistry()
    assert register_installed_features(specs_dir=tmp_path / "nope", registry=registry) == []
    assert len(registry) == 0


def test_discovery_skips_already_registered_names(tmp_path: Path) -> None:
    bundle = _onboard_bundle(tmp_path)
    root = tmp_path / "platform"
    install_bundle(bundle, root=root)

    registry = FeatureRegistry()
    register_installed_features(
        specs_dir=root / "specs", prompts_dir=root / "prompts", registry=registry
    )
    # Re-running against the same registry is a no-op (name already present).
    assert (
        register_installed_features(
            specs_dir=root / "specs", prompts_dir=root / "prompts", registry=registry
        )
        == []
    )


# -- Phase 3: end-to-end activation verification --------------------------------


def test_onboard_activate_run_and_appears_in_dashboard(tmp_path: Path) -> None:
    # 1. Onboard -> bundle.
    bundle = _onboard_bundle(tmp_path)
    root = tmp_path / "platform"

    # 2. Activate (install + discover/register) — registration proven on a local registry.
    installed = install_bundle(bundle, root=root)
    registry = FeatureRegistry()
    assert register_installed_features(
        specs_dir=root / "specs", prompts_dir=root / "prompts", registry=registry
    ) == ["support_cls"]

    # 3. Run an evaluation from the installed artifacts (stub client; no OpenAI).
    spec = load_feature_spec(installed.spec)
    prompts = PromptRegistry.from_directory(root / "prompts")
    feature = build_from_spec(spec, client=_Stub(), prompt_registry=prompts)
    run_registry = FeatureRegistry()
    run_registry.register(feature)
    datasets = DatasetRegistry.from_directory(
        root / "datasets",
        model_resolver=lambda _f: (feature.input_model, feature.output_model),
    )
    engine = EvaluationEngine(features=run_registry, prompts=prompts, datasets=datasets)
    result = engine.run(EvaluationConfig(feature="support_cls", segment_field="category"))
    assert result.aggregate_metrics.total_cases == 4
    assert result.aggregate_metrics.pass_rate == pytest.approx(1.0)

    # 4. Persist -> appears in DashboardData.
    store = EvaluationStore(open_database(":memory:"))
    store.save_evaluation(result, triggered_by="test")
    data = DashboardData(store)
    assert "support_cls" in data.features()
    assert [r.run_uuid for r in data.runs("support_cls")] == [result.run_id]


# -- backward compatibility -----------------------------------------------------


def test_global_registry_only_has_handwritten_features() -> None:
    # No specs/ dir in the repo -> the global discovery hook is a no-op.
    assert feature_registry.names() == ["email_classifier", "ticket_router"]
