"""Lifecycle orchestration: activate a feature end-to-end against the database.

Stitches the existing pieces into the unified Create → Activate → Evaluate flow. It
**uses** the evaluation engine and store but modifies neither. Kept UI-free and
client-injectable so the whole lifecycle is testable offline.

Note: intentionally **not** re-exported from ``activation/__init__`` — importing the
engine here must not be pulled into the lightweight ``features`` import path.
"""

from __future__ import annotations

from collections.abc import Sequence

from mrds.activation.discovery import load_datasets_from_store, load_prompts_from_store
from mrds.activation.errors import ActivationError
from mrds.core.registry import FeatureRegistry
from mrds.datasets.loader import compute_content_hash as compute_dataset_hash
from mrds.db import EvaluationStore
from mrds.evaluation import EvaluationConfig, EvaluationEngine
from mrds.evaluation.models import EvaluationResult
from mrds.features.spec import FeatureSpec, build_from_spec, compute_spec_hash
from mrds.llm.base import StructuredLLMClient
from mrds.onboarding.writer import build_dataset_definition, build_prompt_definition
from mrds.prompts.loader import compute_content_hash as compute_prompt_hash


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
