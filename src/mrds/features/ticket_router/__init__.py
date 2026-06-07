"""The support-ticket-routing feature (the platform's second feature under test)."""

from mrds.features.ticket_router.feature import TicketRouterFeature, build_feature
from mrds.features.ticket_router.schema import (
    TicketCategory,
    TicketPriority,
    TicketRoutingInput,
    TicketRoutingOutput,
)

__all__ = [
    "TicketCategory",
    "TicketPriority",
    "TicketRouterFeature",
    "TicketRoutingInput",
    "TicketRoutingOutput",
    "build_feature",
]
