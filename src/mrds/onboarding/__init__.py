"""Self-service onboarding core (UI-free).

Turns a feature name + family + labeled dataset + instructions into a validated
``FeatureSpec`` plus a loadable prompt/dataset bundle, reusing the spec-driven
generation layer. Importing this package has **no side effects** — no registry
wiring, no global feature discovery.
"""

from mrds.onboarding.errors import OnboardingError
from mrds.onboarding.inference import FeatureFamily, infer_feature_spec
from mrds.onboarding.scaffold import scaffold_prompt
from mrds.onboarding.writer import BundlePaths, write_feature_bundle

__all__ = [
    "BundlePaths",
    "FeatureFamily",
    "OnboardingError",
    "infer_feature_spec",
    "scaffold_prompt",
    "write_feature_bundle",
]
