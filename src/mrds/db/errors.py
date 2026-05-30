"""Error hierarchy for the persistence layer."""

from __future__ import annotations


class DbError(Exception):
    """Base class for persistence errors."""
