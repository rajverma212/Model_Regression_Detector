"""Load a single :class:`FeatureSpec` from a YAML file.

Single-file loading only — deliberately **not** directory auto-discovery or global
registration (those remain deferred). Used to onboard a feature from its declarative
``feature.yaml`` without writing per-feature Python.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from mrds.core.hashing import hash_json
from mrds.features.spec.spec import FeatureSpec


def load_feature_spec(path: str | Path) -> FeatureSpec:
    """Parse and validate a ``feature.yaml`` into a :class:`FeatureSpec`."""
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return FeatureSpec.model_validate(data)


def compute_spec_hash(spec: FeatureSpec) -> str:
    """Content hash identifying a spec, independent of file path or key ordering.

    Used as the ``feature_specs`` identity when persisting a spec to the database, so
    editing a spec's content changes its hash while re-activating identical content
    does not.
    """
    return hash_json(spec.model_dump(mode="json"))
