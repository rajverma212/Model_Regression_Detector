"""Error hierarchy for the feature subsystem."""

from __future__ import annotations


class FeatureError(Exception):
    """Base class for all feature-related errors."""


class FeatureNotFoundError(FeatureError):
    """Raised when a feature name is not present in the registry."""


class FeatureExecutionError(FeatureError):
    """Raised when a feature fails to produce a valid result at runtime."""
