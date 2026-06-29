"""Lifecycle orchestration: activate a bundle, then run its first evaluation.

These helpers stitch the existing pieces into the unified Create → Activate → Evaluate
flow. They **use** the evaluation engine and store but modify neither. Kept UI-free and
client-injectable so the whole lifecycle is testable offline.

Note: intentionally **not** re-exported from ``activation/__init__`` — importing the
engine here must not be pulled into the lightweight ``features`` import path.
"""

from __future__ import annotations

from pathlib import Path

from mrds.activation.discovery import register_installed_features
from mrds.activation.install import InstalledPaths, install_bundle
from mrds.core.registry import FeatureRegistry, feature_registry
from mrds.datasets.registry import DatasetRegistry
from mrds.db import EvaluationStore
from mrds.evaluation import EvaluationConfig, EvaluationEngine
from mrds.evaluation.models import EvaluationResult
from mrds.features.spec import build_from_spec, compute_spec_hash, load_feature_spec
from mrds.llm.base import StructuredLLMClient
from mrds.prompts.registry import PromptRegistry


def activate_bundle(
    bundle_dir: str | Path,
    *,
    root: str | Path,
    registry: FeatureRegistry = feature_registry,
) -> InstalledPaths:
    """Install a generated bundle and register it as a feature (the 'Activate' step)."""
    installed = install_bundle(bundle_dir, root=root)
    register_installed_features(
        specs_dir=Path(root) / "specs", prompts_dir=Path(root) / "prompts", registry=registry
    )
    return installed


def run_first_evaluation(
    installed: InstalledPaths,
    *,
    root: str | Path,
    store: EvaluationStore,
    client: StructuredLLMClient | None = None,
    triggered_by: str = "onboarding",
    max_cases: int | None = None,
) -> EvaluationResult:
    """Run an activated feature's first evaluation and persist it.

    Reuses the unchanged engine. ``client`` is injectable: ``None`` uses the real LLM at
    run time; tests pass a deterministic stub. Returns the persisted result.
    """
    root = Path(root)
    spec = load_feature_spec(installed.spec)
    prompts = PromptRegistry.from_directory(root / "prompts")
    feature = build_from_spec(spec, client=client, prompt_registry=prompts)

    # Scope discovery to *this* feature: ``root/datasets`` is the shared datasets root,
    # so a full ``discover`` would validate every other feature's dataset against this
    # feature's models (the resolver only knows this one). discover_feature loads only
    # ``root/datasets/<feature>``.
    datasets = DatasetRegistry(
        root / "datasets",
        model_resolver=lambda _f: (feature.input_model, feature.output_model),
    )
    datasets.discover_feature(spec.feature_name)
    registry = FeatureRegistry()
    registry.register(feature)
    engine = EvaluationEngine(features=registry, prompts=prompts, datasets=datasets)

    result = engine.run(
        EvaluationConfig(
            feature=spec.feature_name, segment_field=spec.segment_field, max_cases=max_cases
        )
    )
    # Persist the spec into the DB system of record alongside the run (Phase 2): the
    # feature's definition now lives in the database, not only as specs/<name>.yaml.
    # The filesystem copy is still written by install_bundle and remains the discovery
    # source until the cutover in later phases.
    store.feature_specs.upsert(
        feature_name=spec.feature_name,
        content_hash=compute_spec_hash(spec),
        spec_json=spec.model_dump_json(),
        segment_field=spec.segment_field,
    )
    store.save_evaluation(result, triggered_by=triggered_by)
    return result
