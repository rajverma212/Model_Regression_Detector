"""Tests for the feature registry and feature registration."""

from __future__ import annotations

import pytest

from mrds.core.errors import FeatureError, FeatureNotFoundError
from mrds.core.interfaces import Feature
from mrds.core.registry import FeatureRegistry, feature_registry
from mrds.features.email_classifier import EmailClassifierFeature


def test_email_classifier_is_registered_on_import() -> None:
    # Importing mrds.features (transitively via the feature import above) registers it.
    import mrds.features  # noqa: F401

    assert "email_classifier" in feature_registry
    feature = feature_registry.get("email_classifier")
    assert isinstance(feature, Feature)
    assert "email_classifier" in feature_registry.names()


def test_register_and_get_roundtrip() -> None:
    registry = FeatureRegistry()
    registry.register(EmailClassifierFeature())
    assert len(registry) == 1
    assert registry.get("email_classifier").name == "email_classifier"


def test_duplicate_registration_raises() -> None:
    registry = FeatureRegistry()
    registry.register(EmailClassifierFeature())
    with pytest.raises(FeatureError):
        registry.register(EmailClassifierFeature())


def test_unknown_feature_raises() -> None:
    registry = FeatureRegistry()
    with pytest.raises(FeatureNotFoundError):
        registry.get("does_not_exist")


def test_register_rejects_non_feature() -> None:
    registry = FeatureRegistry()
    with pytest.raises(FeatureError):
        registry.register(object())  # type: ignore[arg-type]
