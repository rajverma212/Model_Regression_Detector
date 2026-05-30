"""``mrds evaluate`` — run an evaluation and persist the result."""

from __future__ import annotations

import argparse
from typing import TYPE_CHECKING

from mrds.cli.exit_codes import EXIT_OK
from mrds.evaluation import EvaluationConfig
from mrds.observability.logging import get_logger

if TYPE_CHECKING:
    from mrds.cli.runtime import CliRuntime

logger = get_logger(__name__)


def configure(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("evaluate", help="Run an evaluation and persist the result.")
    parser.add_argument("--feature", required=True, help="Registered feature to evaluate.")
    parser.add_argument("--prompt-version", default=None, help="Prompt version (default: latest).")
    parser.add_argument(
        "--dataset-version", default=None, help="Dataset version (default: latest)."
    )
    parser.add_argument(
        "--segment-field", default=None, help="Expected-output field to segment metrics by."
    )
    parser.add_argument("--max-cases", type=int, default=None, help="Cap cases (smoke runs).")
    parser.add_argument("--judge", action="store_true", help="Record that LLM-as-judge ran.")
    parser.add_argument("--triggered-by", choices=("local", "ci", "manual"), default="local")
    parser.add_argument("--git-sha", default=None, help="Commit under test (CI).")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace, runtime: CliRuntime) -> int:
    config = EvaluationConfig(
        feature=args.feature,
        prompt_version=args.prompt_version,
        dataset_version=args.dataset_version,
        segment_field=args.segment_field,
        max_cases=args.max_cases,
    )
    result = runtime.engine.run(config)
    runtime.store.save_evaluation(
        result,
        triggered_by=args.triggered_by,
        git_sha=args.git_sha,
        judge_enabled=args.judge,
    )

    metrics = result.aggregate_metrics
    print(f"run_id: {result.run_id}")
    print(
        f"feature={result.feature} prompt={result.prompt_version} "
        f"dataset={result.dataset_version} model={result.model}"
    )
    print(
        f"cases={metrics.total_cases} passed={metrics.passed} failed={metrics.failed} "
        f"errored={metrics.errored} pass_rate={metrics.pass_rate:.3f}"
    )
    logger.info("evaluate persisted run %s for %s", result.run_id, result.feature)
    return EXIT_OK
