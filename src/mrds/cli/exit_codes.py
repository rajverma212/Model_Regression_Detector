"""Process exit codes used across CLI commands.

These are the contract GitHub Actions keys the merge gate off of:
``compare`` returns ``EXIT_BLOCKED`` on a critical (blocking) regression.
"""

from __future__ import annotations

EXIT_OK = 0
EXIT_BLOCKED = 1
EXIT_ERROR = 2
