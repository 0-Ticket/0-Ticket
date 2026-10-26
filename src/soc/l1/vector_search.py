"""Stand-in for the Ticket vector service when it cannot be opened (box 11, #105).

``build_runtime`` assembles L1 from replaceable services. When the one that answers
similar-Ticket searches cannot be initialized, L1 keeps starting with this stand-in in
its place: the search path is disabled for the life of the process, every other step
runs as before, and the holds of D-034 and D-036 stay the only reasons to stop a
Ticket. The stand-in names no backend, so the L1 core does not learn which store or
embedding model was configured.
"""

from collections.abc import Mapping, Sequence
from typing import Any


class SearchUnavailableError(RuntimeError):
    """The search path is disabled because its service could not be initialized."""


class UnavailableTicketSearch:
    """Answer every search and index call with ``SearchUnavailableError``."""

    def search_by_ticket(self, ticket: Mapping[str, Any], *, k: int = 5) -> list[Any]:
        raise SearchUnavailableError("ticket_search_unavailable")

    def search_by_entities(
        self,
        entities: Sequence[Mapping[str, Any]],
        sentence: str,
        *,
        k: int = 5,
    ) -> list[Any]:
        raise SearchUnavailableError("ticket_search_unavailable")

    def add_decided_ticket(self, ticket: Mapping[str, Any]) -> None:
        raise SearchUnavailableError("ticket_index_unavailable")

    def close(self) -> None:
        return None
