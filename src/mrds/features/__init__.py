"""Feature package — the backbone of the platform.

Importing this package registers every built-in feature into the global
:data:`mrds.core.registry.feature_registry`. The evaluation engine (Sprint 5) and
CLI rely on that side effect: ``import mrds.features`` makes all features
discoverable by name. Future features are added here exactly like the email
classifier — implement :class:`~mrds.core.interfaces.Feature`, then register it.
"""

from mrds.core.registry import feature_registry
from mrds.features.email_classifier import build_feature as build_email_classifier
from mrds.features.ticket_router import build_feature as build_ticket_router
from mrds.observability.logging import get_logger

logger = get_logger(__name__)

# Factories for every built-in feature. Add future features to this mapping.
_FEATURE_FACTORIES = {
    "email_classifier": build_email_classifier,
    "ticket_router": build_ticket_router,
}


def register_all() -> None:
    """Register all built-in features (idempotent)."""
    for name, factory in _FEATURE_FACTORIES.items():
        if name not in feature_registry:
            feature_registry.register(factory())


def _register_installed_features() -> None:
    """Register any activated spec-driven features (no-op if none are installed).

    Optional and best-effort: a discovery failure must never prevent the hand-coded
    features above from registering, so errors are logged and swallowed.
    """
    try:
        from mrds.activation.discovery import register_installed_features

        register_installed_features()
    except Exception:  # noqa: BLE001 - discovery is optional; never break core registration
        logger.warning("Spec discovery failed; installed features not registered", exc_info=True)


register_all()
_register_installed_features()
