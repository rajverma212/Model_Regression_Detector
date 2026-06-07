"""Deterministic, offline demo-data support.

Populates the SQLite system of record with a realistic evaluation history (a
promoted baseline, several runs, and warning + critical regressions) using the
real platform pipeline and a fake LLM client — no OpenAI, no network.
"""

from mrds.demo.client import DeterministicEmailClient
from mrds.demo.generator import (
    DEFAULT_DEMO_CONFIG,
    DEFAULT_RUNS,
    DemoConfig,
    DemoRunSpec,
)
from mrds.demo.seed import SeedResult, seed_demo
from mrds.demo.ticket_client import DeterministicTicketRouterClient

__all__ = [
    "DEFAULT_DEMO_CONFIG",
    "DEFAULT_RUNS",
    "DemoConfig",
    "DemoRunSpec",
    "DeterministicEmailClient",
    "DeterministicTicketRouterClient",
    "SeedResult",
    "seed_demo",
]
