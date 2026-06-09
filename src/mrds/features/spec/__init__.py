"""Spec-driven feature generation (Phase 1).

A self-contained layer that turns a declarative :class:`FeatureSpec` into runtime
``Feature`` and ``Scorer`` objects — dynamic models, dynamic enums, library scorers,
and a :class:`GenericStructuredFeature`. Importing this package has **no side
effects**: it does not touch the global feature registry or any core subsystem.
"""

from mrds.features.spec.feature import GenericStructuredFeature, build_from_spec
from mrds.features.spec.loader import load_feature_spec
from mrds.features.spec.models import (
    build_enum,
    build_input_model,
    build_model,
    build_output_model,
)
from mrds.features.spec.scorers import (
    ExactMatchScorer,
    TextBoundsScorer,
    build_scorer,
)
from mrds.features.spec.spec import (
    FeatureSpec,
    FieldSpec,
    FieldType,
    ScorerKind,
    ScorerParams,
    ScorerSpec,
    SpecError,
)

__all__ = [
    "ExactMatchScorer",
    "FeatureSpec",
    "FieldSpec",
    "FieldType",
    "GenericStructuredFeature",
    "ScorerKind",
    "ScorerParams",
    "ScorerSpec",
    "SpecError",
    "TextBoundsScorer",
    "build_enum",
    "build_from_spec",
    "build_input_model",
    "build_model",
    "build_output_model",
    "build_scorer",
    "load_feature_spec",
]
