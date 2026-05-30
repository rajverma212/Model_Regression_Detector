"""``mrds promote-baseline`` — promote a persisted run to the active baseline."""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from mrds.cli.exit_codes import EXIT_ERROR, EXIT_OK
from mrds.observability.logging import get_logger
from mrds.regression import Baseline, BaselineCandidate, BaselinePromoter

if TYPE_CHECKING:
    from mrds.cli.runtime import CliRuntime

logger = get_logger(__name__)


def configure(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "promote-baseline", help="Promote a run to the active baseline for its feature."
    )
    parser.add_argument("--run", required=True, help="Run id to promote.")
    parser.add_argument("--promoted-by", default="cli", help="Who/what is promoting.")
    parser.add_argument("--note", default="", help="Promotion note.")
    parser.add_argument(
        "--force", action="store_true", help="Promote even if not eligible (e.g. a regression)."
    )
    parser.set_defaults(func=run)


def run(args: argparse.Namespace, runtime: CliRuntime) -> int:
    store = runtime.store

    candidate_result = store.get_evaluation_result(args.run)
    if candidate_result is None:
        print(f"error: run '{args.run}' not found", file=sys.stderr)
        return EXIT_ERROR

    feature = candidate_result.feature
    current_result = store.get_active_baseline_result(feature)
    current = (
        Baseline(
            feature=feature,
            result=current_result,
            promoted_at=datetime.now(UTC),
            promoted_by="",
        )
        if current_result is not None
        else None
    )

    promoter = BaselinePromoter(runtime.detector)
    eligibility = promoter.check(BaselineCandidate(result=candidate_result), current)

    if not eligibility.eligible and not args.force:
        print(f"Not eligible to promote run {args.run}:", file=sys.stderr)
        for reason in eligibility.reasons:
            print(f"  - {reason}", file=sys.stderr)
        print("Re-run with --force to override.", file=sys.stderr)
        return EXIT_ERROR

    record = store.promote_baseline(args.run, promoted_by=args.promoted_by, note=args.note)
    print(f"Promoted run {args.run} as baseline for {feature} (baseline_id={record.id}).")
    if eligibility.severity is not None:
        print(f"severity vs previous baseline: {eligibility.severity.value}")
    if args.force and not eligibility.eligible:
        print("(forced promotion despite ineligibility)")
    logger.info("promoted baseline for %s -> run %s", feature, args.run)
    return EXIT_OK
