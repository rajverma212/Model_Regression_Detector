"""Feature activation: install a generated bundle and register it as a feature.

Reuses the spec-driven generation layer; touches no core subsystem (engine,
regression detector, DB schema, dashboard, reporting, alerting).
"""

from mrds.activation.discovery import (
    DEFAULT_SPECS_DIR,
    discover_specs,
    register_installed_features,
)
from mrds.activation.errors import ActivationError

__all__ = [
    "DEFAULT_SPECS_DIR",
    "ActivationError",
    "discover_specs",
    "register_installed_features",
]
