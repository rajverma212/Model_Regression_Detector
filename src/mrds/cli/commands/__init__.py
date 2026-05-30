"""CLI subcommands. Each module exposes ``configure(subparsers)`` and ``run(args, runtime)``."""

from mrds.cli.commands import compare, evaluate, promote_baseline, report

#: All command modules, in help/registration order.
COMMAND_MODULES = (evaluate, compare, report, promote_baseline)

__all__ = ["COMMAND_MODULES", "compare", "evaluate", "promote_baseline", "report"]
