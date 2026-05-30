"""MRDS command-line entrypoint.

The single, CLI-first entrypoint used both locally and in CI. It wires the four
commands (``evaluate``, ``compare``, ``report``, ``promote-baseline``) to the
platform's subsystems via a :class:`CliRuntime`. Known errors are turned into a
friendly message and a non-zero exit code; ``compare`` additionally returns
``EXIT_BLOCKED`` (1) on a blocking regression — the CI merge gate.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from pydantic import ValidationError

from mrds import __version__
from mrds.cli.commands import COMMAND_MODULES
from mrds.cli.exit_codes import EXIT_ERROR, EXIT_OK
from mrds.cli.runtime import CliRuntime, build_runtime
from mrds.config.settings import get_settings
from mrds.core.errors import FeatureError
from mrds.datasets.errors import DatasetError
from mrds.db import DbError
from mrds.evaluation import EvaluationError
from mrds.observability.logging import configure_logging, get_logger
from mrds.prompts.errors import PromptError
from mrds.regression import RegressionError

logger = get_logger(__name__)

# Errors that represent user/runtime problems (not bugs): reported cleanly.
_KNOWN_ERRORS = (
    FeatureError,
    PromptError,
    DatasetError,
    EvaluationError,
    RegressionError,
    DbError,
    ValidationError,
    ValueError,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level parser with every command registered."""
    parser = argparse.ArgumentParser(
        prog="mrds",
        description="Model Regression Detection System — AI evaluation & deployment-safety CLI.",
    )
    parser.add_argument("--version", action="version", version=f"mrds {__version__}")
    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    for module in COMMAND_MODULES:
        module.configure(subparsers)
    return parser


def main(argv: Sequence[str] | None = None, *, runtime: CliRuntime | None = None) -> int:
    """CLI entrypoint. Returns a process exit code."""
    settings = get_settings()
    configure_logging(level=settings.log_level, json_logs=settings.json_logs)

    parser = build_parser()
    args = parser.parse_args(argv)

    if not getattr(args, "command", None):
        parser.print_help()
        return EXIT_OK

    runtime = runtime or build_runtime()
    try:
        return int(args.func(args, runtime))
    except _KNOWN_ERRORS as exc:
        logger.error("%s failed: %s", args.command, exc)
        print(f"error: {exc}", file=sys.stderr)
        return EXIT_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
