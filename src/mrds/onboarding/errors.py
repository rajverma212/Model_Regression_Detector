"""Errors for the self-service onboarding core."""

from __future__ import annotations


class OnboardingError(Exception):
    """Raised when an onboarding input is invalid or a bundle cannot be produced."""
