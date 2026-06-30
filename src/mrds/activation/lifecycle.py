"""Lifecycle orchestration: activate a bundle, then run its first evaluation.

These helpers stitch the existing pieces into the unified Create → Activate → Evaluate
flow. They **use** the evaluation engine and store but modify neither. Kept UI-free and
client-injectable so the whole lifecycle is testable offline.

Note: intentionally **not** re-exported from ``activation/__init__`` — importing the
engine here must not be pulled into the lightweight ``features`` import path.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from mrds.activation.discovery import (
    load_datasets_from_store,
    load_prompts_from_store,
    register_installed_features,
)
from mrds.activation.errors import ActivationError
from mrds.activation.install import InstalledPaths, install_bundle
from mrds.core.registry import FeatureRegistry, feature_registry
from mrds.datasets.loader import compute_content_hash as compute_dataset_hash
from mrds.datasets.registry import DatasetRegistry
from mrds.db import EvaluationStore
from mrds.evaluation import EvaluationConfig, EvaluationEngine
from mrds.evaluation.models import EvaluationResult
from mrds.features.spec import FeatureSpec, build_from_spec, compute_spec_hash, load_feature_spec
from mrds.llm.base import StructuredLLMClient
from mrds.onboarding.writer import build_dataset_definition, build_prompt_definition
from mrds.prompts.loader import compute_content_hash as compute_prompt_hash
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
    # Persist the spec, prompt, and dataset into the DB system of record alongside the
    # run (Phases 2-4): the feature's definition, prompt body, and labeled cases now
    # live in the database, not only as specs/<name>.yaml, prompts/<name>/v1.yaml, and
    # datasets/<name>/v1.json. The filesystem copies are still written by install_bundle
    # and remain the resolution source until the cutover in later phases.
    store.feature_specs.upsert(
        feature_name=spec.feature_name,
        content_hash=compute_spec_hash(spec),
        spec_json=spec.model_dump_json(),
        segment_field=spec.segment_field,
    )
    prompt = prompts.get_latest(spec.resolved_prompt_feature)
    store.prompt_versions.upsert(
        feature_name=spec.feature_name,
        version=prompt.version,
        content_hash=prompt.content_hash,
        path=str(prompt.source_path),
        content=prompt.definition.model_dump_json(),
    )
    dataset = datasets.get_latest(spec.feature_name)
    store.dataset_versions.upsert(
        feature_name=spec.feature_name,
        version=dataset.version,
        content_hash=dataset.content_hash,
        case_count=dataset.case_count,
        path=str(dataset.source_path),
        content=dataset.definition.model_dump_json(),
    )
    store.save_evaluation(result, triggered_by=triggered_by)
    return result


def activate_feature_from_store(
    spec: FeatureSpec,
    *,
    cases: Sequence[dict],
    system_prompt: str,
    store: EvaluationStore,
    client: StructuredLLMClient | None = None,
    triggered_by: str = "onboarding",
    max_cases: int | None = None,
) -> EvaluationResult:
    """Activate a feature end-to-end against the database — **no filesystem required**.

    The DB-native counterpart to ``activate_bundle`` + ``run_first_evaluation``: it builds
    the prompt and dataset definitions in memory, persists the spec/prompt/dataset to the
    store, rebuilds the prompt and dataset registries *from the store*, runs the first
    evaluation through the unchanged engine, and persists the run — writing and reading no
    bundle files. Use it where the platform root is not writable (read-only serverless
    filesystems); the database is the system of record.

    Raises:
        ActivationError: if the feature is already activated (its spec is persisted).
    """
    if store.feature_specs.get(spec.feature_name) is not None:
        raise ActivationError(f"feature '{spec.feature_name}' is already activated")

    prompt_def = build_prompt_definition(spec, system_prompt)
    dataset_def = build_dataset_definition(spec, cases)

    # Persist the full bundle into the system of record. These writes share the
    # connection's pending transaction and commit atomically with the run below.
    store.feature_specs.upsert(
        feature_name=spec.feature_name,
        content_hash=compute_spec_hash(spec),
        spec_json=spec.model_dump_json(),
        segment_field=spec.segment_field,
    )
    store.prompt_versions.upsert(
        feature_name=spec.feature_name,
        version=prompt_def.version,
        content_hash=compute_prompt_hash(prompt_def),
        content=prompt_def.model_dump_json(),
    )
    store.dataset_versions.upsert(
        feature_name=spec.feature_name,
        version=dataset_def.version,
        content_hash=compute_dataset_hash(dataset_def),
        case_count=dataset_def.case_count,
        content=dataset_def.model_dump_json(),
    )

    # Rebuild the registries from the database (closing the loop: persist -> read) and run
    # the first evaluation through the unchanged engine — never touching the filesystem.
    prompts = load_prompts_from_store(store)
    feature = build_from_spec(spec, client=client, prompt_registry=prompts)
    datasets = load_datasets_from_store(
        store, model_resolver=lambda _f: (feature.input_model, feature.output_model)
    )
    registry = FeatureRegistry()
    registry.register(feature)
    engine = EvaluationEngine(features=registry, prompts=prompts, datasets=datasets)
    result = engine.run(
        EvaluationConfig(
            feature=spec.feature_name, segment_field=spec.segment_field, max_cases=max_cases
        )
    )
    store.save_evaluation(result, triggered_by=triggered_by)
    return result
