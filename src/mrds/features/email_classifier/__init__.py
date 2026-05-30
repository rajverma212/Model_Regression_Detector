"""The customer-support email-classification feature (the first feature under test)."""

from mrds.features.email_classifier.feature import EmailClassifierFeature, build_feature
from mrds.features.email_classifier.schema import (
    EmailCategory,
    EmailClassificationInput,
    EmailClassificationOutput,
)

__all__ = [
    "EmailCategory",
    "EmailClassificationInput",
    "EmailClassificationOutput",
    "EmailClassifierFeature",
    "build_feature",
]
