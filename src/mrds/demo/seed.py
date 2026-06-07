"""Seed routine: populate the database with the demo narrative.

Reuses the *real* platform end-to-end — :class:`EvaluationEngine`,
:class:`EvaluationStore`, :class:`RegressionDetector`, and :class:`BaselinePromoter`
— so the demo exercises (and proves) the actual pipeline. Nothing is bypassed.

The routine is idempotent: if the database already contains any runs it does
nothing. It is deterministic and fully offline (no OpenAI, no network).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from mrds.core.registry import FeatureRegistry
from mrds.datasets.loader import DEFAULT_DATASETS_DIR
from mrds.datasets.registry import DatasetRegistry
from mrds.db import EvaluationStore
from mrds.demo.generator import (
    DEFAULT_DEMO_CONFIG,
    DemoConfig,
    build_client,
    build_oracle,
)
from mrds.demo.ticket_client import DeterministicTicketRouterClient
from mrds.evaluation import EvaluationConfig, EvaluationEngine
from mrds.features.email_classifier import EmailClassifierFeature
from mrds.features.ticket_router import TicketRouterFeature
from mrds.observability.logging import get_logger
from mrds.prompts.loader import DEFAULT_PROMPTS_DIR
from mrds.prompts.registry import PromptRegistry
from mrds.regression import BaselineCandidate, BaselinePromoter, RegressionDetector

logger = get_logger(__name__)


@dataclass(frozen=True)
class SeedResult:
    """Summary of a seeding attempt."""

    seeded: bool
    run_ids: tuple[str, ...] = ()
    baseline_run_id: str | None = None
    warning_run_ids: tuple[str, ...] = field(default_factory=tuple)
    critical_run_ids: tuple[str, ...] = field(default_factory=tuple)


def seed_demo(
    store: EvaluationStore,
    *,
    config: DemoConfig = DEFAULT_DEMO_CONFIG,
    prompts_dir=DEFAULT_PROMPTS_DIR,
    datasets_dir=DEFAULT_DATASETS_DIR,
) -> SeedResult:
    """Seed deterministic demo data if (and only if) the database is empty."""
    if store.runs.features():
        logger.info("Demo seed skipped: database already contains runs.")
        return SeedResult(seeded=False)

    prompts = PromptRegistry.from_directory(prompts_dir)
    # Default (registry-based) resolver so each feature's dataset resolves to its own
    # models — required now that the datasets directory holds more than one feature.
    datasets = DatasetRegistry.from_directory(datasets_dir)
    cases = list(datasets.get_latest(config.feature).definition.cases)
    if config.max_cases is not None:
        cases = cases[: config.max_cases]
    oracle, ordered_texts = build_oracle(cases)

    detector = RegressionDetector()
    promoter = BaselinePromoter(detector)

    run_ids: list[str] = []
    baseline_run_id: str | None = None
    warning_run_ids: list[str] = []
    critical_run_ids: list[str] = []

    for spec in config.runs:
        client = build_client(
            spec,
            oracle=oracle,
            ordered_texts=ordered_texts,
            summary=config.summary,
            simulate_latency=config.simulate_latency,
        )
        feature = EmailClassifierFeature(client=client, prompt_registry=prompts)
        registry = FeatureRegistry()
        registry.register(feature)
        engine = EvaluationEngine(features=registry, prompts=prompts, datasets=datasets)

        result = engine.run(
            EvaluationConfig(
                feature=config.feature,
                segment_field=config.segment_field,
                max_cases=config.max_cases,
            )
        )
        store.save_evaluation(result, triggered_by="demo")
        run_ids.append(result.run_id)

        if spec.role == "baseline":
            eligibility = promoter.check(BaselineCandidate(result=result), current=None)
            if eligibility.eligible:
                store.promote_baseline(
                    result.run_id, promoted_by="demo", note="Initial demo baseline"
                )
                baseline_run_id = result.run_id
        elif spec.role in ("warning", "critical"):
            baseline = store.get_active_baseline_result(config.feature)
            if baseline is not None:
                regression = detector.compare(baseline, result)
                store.save_regression(regression)
                if spec.role == "warning":
                    warning_run_ids.append(result.run_id)
                else:
                    critical_run_ids.append(result.run_id)

    # Additively seed a second feature so the demo dashboard is multi-feature. This is
    # independent of the email narrative above and does not affect the returned result.
    _seed_ticket_router(store, config=config, prompts_dir=prompts_dir, datasets_dir=datasets_dir)

    logger.info(
        "Seeded demo data: %d runs (baseline=%s, warnings=%d, criticals=%d)",
        len(run_ids),
        baseline_run_id,
        len(warning_run_ids),
        len(critical_run_ids),
    )
    return SeedResult(
        seeded=True,
        run_ids=tuple(run_ids),
        baseline_run_id=baseline_run_id,
        warning_run_ids=tuple(warning_run_ids),
        critical_run_ids=tuple(critical_run_ids),
    )


def _seed_ticket_router(
    store: EvaluationStore,
    *,
    config: DemoConfig,
    prompts_dir: object = DEFAULT_PROMPTS_DIR,
    datasets_dir: object = DEFAULT_DATASETS_DIR,
) -> None:
    """Seed a small ticket-router narrative: a promoted baseline + a critical regression.

    Drives the *real* pipeline (engine, store, detector, promoter) with a deterministic
    offline client — proving a second feature evaluates end-to-end with no core changes.
    """
    feature_name = "ticket_router"
    prompts = PromptRegistry.from_directory(prompts_dir)
    datasets = DatasetRegistry.from_directory(datasets_dir)
    cases = list(datasets.get_latest(feature_name).definition.cases)
    oracle = {
        case.input.ticket_text: (
            case.expected_output.category.value,
            case.expected_output.priority.value,
        )
        for case in cases
    }
    ordered_texts = [case.input.ticket_text for case in cases]

    detector = RegressionDetector()
    promoter = BaselinePromoter(detector)

    # (role, number of last cases to misclassify, token scale, latency ms)
    specs = (("baseline", 1, 1.0, 11.0), ("critical", 7, 1.0, 12.0))
    for role, wrong_count, token_scale, latency_ms in specs:
        wrong_texts = (
            frozenset(ordered_texts[len(ordered_texts) - wrong_count :])
            if wrong_count > 0
            else frozenset()
        )
        client = DeterministicTicketRouterClient(
            oracle=oracle,
            wrong_texts=wrong_texts,
            token_scale=token_scale,
            latency_ms=latency_ms,
            simulate_latency=config.simulate_latency,
        )
        feature = TicketRouterFeature(client=client, prompt_registry=prompts)
        registry = FeatureRegistry()
        registry.register(feature)
        engine = EvaluationEngine(features=registry, prompts=prompts, datasets=datasets)

        result = engine.run(EvaluationConfig(feature=feature_name, segment_field="category"))
        store.save_evaluation(result, triggered_by="demo")

        if role == "baseline":
            eligibility = promoter.check(BaselineCandidate(result=result), current=None)
            if eligibility.eligible:
                store.promote_baseline(
                    result.run_id, promoted_by="demo", note="Initial ticket-router baseline"
                )
        else:
            baseline = store.get_active_baseline_result(feature_name)
            if baseline is not None:
                store.save_regression(detector.compare(baseline, result))

    logger.info("Seeded ticket_router demo (%d runs).", len(specs))
