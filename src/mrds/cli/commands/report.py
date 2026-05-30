"""``mrds report`` — render HTML and Markdown reports for a persisted run."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from mrds.cli.exit_codes import EXIT_ERROR, EXIT_OK
from mrds.observability.logging import get_logger
from mrds.reporting import ReportFormat, save_report

if TYPE_CHECKING:
    from mrds.cli.runtime import CliRuntime

logger = get_logger(__name__)


def configure(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("report", help="Render reports for a stored run.")
    parser.add_argument("--run", default=None, help="Run id to report on.")
    parser.add_argument(
        "--feature", default=None, help="Use the latest run for this feature if --run is omitted."
    )
    parser.add_argument("--format", choices=("html", "markdown", "both"), default="both")
    parser.add_argument("--output-dir", default="reports", help="Directory to write reports to.")
    parser.set_defaults(func=run)


def run(args: argparse.Namespace, runtime: CliRuntime) -> int:
    store = runtime.store

    run_uuid = args.run or (store.latest_run_uuid(args.feature) if args.feature else None)
    if run_uuid is None:
        print("error: provide --run or --feature", file=sys.stderr)
        return EXIT_ERROR

    result = store.get_evaluation_result(run_uuid)
    if result is None:
        print(f"error: run '{run_uuid}' not found", file=sys.stderr)
        return EXIT_ERROR

    base = Path(args.output_dir) / result.feature
    written: list[Path] = []
    if args.format in ("html", "both"):
        report = runtime.reporter.render_evaluation(result, ReportFormat.HTML)
        written.append(save_report(report, base / f"{run_uuid}.html"))
    if args.format in ("markdown", "both"):
        report = runtime.reporter.render_evaluation(result, ReportFormat.MARKDOWN)
        written.append(save_report(report, base / f"{run_uuid}.md"))

    for path in written:
        print(f"report: {path}")
    logger.info("report wrote %d file(s) for run %s", len(written), run_uuid)
    return EXIT_OK
