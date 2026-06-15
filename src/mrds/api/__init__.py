"""HTTP API for the MRDS evaluation platform (the web frontend's backend).

A thin, feature-agnostic FastAPI surface over the existing read-only data layer and
the baseline-promotion path. No evaluation logic lives here — it only *serves* what the
platform already computes. Start it with ``python -m mrds.api``.
"""

from mrds.api.app import app, create_app

__all__ = ["app", "create_app"]
