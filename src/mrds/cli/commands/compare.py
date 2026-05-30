"""``mrds compare`` — compare a run to the active baseline and gate on regressions."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from mrds.cli.exit_codes import EXIT_BLOCKED, EXIT_ERROR, EXIT_OK
from mrds.observability.logging import get_logger
from mrds.regression.models import RegressionResult
from mrds.reporting import ReportBuilder, ReportFormat, save_report

if TYPE_CHECKING:
    from mrds.cli.runtime import CliRuntime

logger = get_logger(__name__)


def configure(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "compare", help="Compare a run to the active baseline; gate on blocking regressions."
    )
    parser.add_argument("--feature", required=True, help="Feature whose baseline to compare to.")
    parser.add_argument("--run", default=None, help="Candidate run id (default: latest run).")
    parser.add_argument(
        "--report",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Write a regression report (default: on).",
    )
    parser.add_argument("--report-dir", default="reports", help="Directory for regression reports.")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace, runtime: CliRuntime) -> int:
    store = runtime.store

    candidate_uuid = args.run or store.latest_run_uuid(args.feature)
    if candidate_uuid is None:
        print(f"error: no runs found for feature '{args.feature}'", file=sys.stderr)
        return EXIT_ERROR

    candidate = store.get_evaluation_result(candidate_uuid)
    if candidate is None:
        print(f"error: run '{candidate_uuid}' not found", file=sys.stderr)
        return EXIT_ERROR

    baseline = store.get_active_baseline_result(args.feature)
    if baseline is None:
        print(
            f"No active baseline for '{args.feature}'; nothing to compare. "
            "Promote a baseline first."
        )
        return EXIT_OK

    regression = runtime.detector.compare(baseline, candidate)
    store.save_regression(regression)

    if args.report:
        for path in _write_reports(runtime.reporter, regression, args.report_dir):
            print(f"report: {path}")

    print(f"baseline={regression.baseline_run_id} candidate={regression.candidate_run_id}")
    print(
        f"severity={regression.severity.value} "
        f"warnings={regression.warning_count} critical={regression.critical_count}"
    )
    for metric in regression.regressions:
        print(f"  - {metric.name}: {metric.reason} [{metric.severity.value}]")

    if regression.is_blocking:
        print("RESULT: blocking regression detected — failing.", file=sys.stderr)
        return EXIT_BLOCKED
    print("RESULT: no blocking regression.")
    return EXIT_OK


def _write_reports(
    reporter: ReportBuilder, regression: RegressionResult, report_dir: str
) -> list[Path]:
    base = Path(report_dir) / regression.feature
    html = reporter.render_regression(regression, fmt=ReportFormat.HTML)
    markdown = reporter.render_regression(regression, fmt=ReportFormat.MARKDOWN)
    return [
        save_report(html, base / f"{regression.candidate_run_id}.regression.html"),
        save_report(markdown, base / f"{regression.candidate_run_id}.regression.md"),
    ]
