"""Ticket lifecycle and store boundary (box 10, C5 -> C6)."""

import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from soc.contracts import Ticket, validate_contract
from soc.store.paging import (
    DEFAULT_PAGE_LIMIT,
    check_filter,
    check_page_limit,
    decode_cursor,
    encode_cursor,
    literal_values,
)

ALLOWED_TICKET_TRANSITIONS = {
    "new": frozenset({"triaging"}),
    "triaging": frozenset({"on_hold", "closed_benign", "closed_fp", "l2_escalated"}),
}
DECIDED_TICKET_STATUSES = frozenset({"closed_benign", "closed_fp", "l2_escalated"})
TICKET_STATUSES = literal_values(Ticket, "status")
TICKET_ORIGINS = literal_values(Ticket, "origin")


class InvalidTicketTransition(ValueError):
    """The requested Ticket status edge is outside the C6 v2 lifecycle."""


class TicketNotFoundError(LookupError):
    """No Ticket exists for the requested ID."""


class ConcurrentTicketUpdateError(RuntimeError):
    """A Ticket changed since the caller read its expected status."""


class TicketNotDecidedError(ValueError):
    """Only completed Ticket decisions can be sent to the vector index boundary."""


@dataclass(frozen=True)
class TicketPage:
    """One page of C6 in list order. ``next_cursor`` is None on the last page."""

    items: list[dict[str, Any]]
    next_cursor: str | None


class TicketStore(Protocol):
    """Storage operations required by the Ticket lifecycle."""

    def create(self, ticket: Mapping[str, Any]) -> dict[str, Any]: ...

    def get(self, ticket_id: str) -> dict[str, Any] | None: ...

    def find_by_entity(self, entity_type: str, entity_value: str) -> list[dict[str, Any]]: ...

    def update(self, ticket: Mapping[str, Any], *, expected_status: str) -> dict[str, Any]: ...

    def close(self) -> None: ...

    def list(
        self,
        *,
        status: str | None = None,
        origin: str | None = None,
        handling_type: str | None = None,
        min_priority: int | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_LIMIT,
    ) -> TicketPage:
        """C6 matching the filters in ``GET /api/tickets`` order, ``limit`` (1-200) per page.

        Order: ``priority`` descending, then ``created_at``, then ``ticket_id``
        (docs/api-contracts.md). Check the arguments with ``check_ticket_list_args``
        and page with ``ticket_cursor`` / ``decode_ticket_cursor``.

        Every filter is applied before the page is cut: filtering a page after
        reading it would leave gaps and empty pages (docs/api-contracts.md).
        """
        ...


class TicketVectorSink(Protocol):
    """Interface for the later Vector DB integration; this box supplies no backend."""

    def add_decided_ticket(self, ticket: Mapping[str, Any]) -> None: ...


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _new_ticket_id() -> str:
    return f"tk_{uuid.uuid4().hex}"


def _contract_dict(name: str, value: Mapping[str, Any]) -> dict[str, Any]:
    return validate_contract(name, dict(value)).model_dump(mode="json")


def check_ticket_list_args(
    *,
    status: str | None = None,
    origin: str | None = None,
    handling_type: str | None = None,
    min_priority: int | None = None,
    limit: int = DEFAULT_PAGE_LIMIT,
) -> None:
    """Check the ``GET /api/tickets`` filters and ``limit``; otherwise ValueError.

    ``status`` and ``origin`` are C6 enums. ``handling_type`` is a registered
    value, so it is compared as the string it arrives as instead of being
    limited to a fixed list (``docs/extensibility.md``). ``min_priority`` keeps
    Tickets whose C6 ``priority`` is at least that value.
    """
    check_filter("status", status, TICKET_STATUSES)
    check_filter("origin", origin, TICKET_ORIGINS)
    if handling_type is not None and not handling_type:
        raise ValueError("handling_type must not be empty")
    if min_priority is not None:
        # bool is an int in Python; it is not a priority.
        if isinstance(min_priority, bool) or not isinstance(min_priority, int):
            raise ValueError("min_priority must be an integer")
        if min_priority < 0:
            raise ValueError("min_priority must be 0 or more")
    check_page_limit(limit)


def ticket_sort_key(ticket: Mapping[str, Any]) -> tuple[int, int, str]:
    """Ascending key for ``GET /api/tickets`` order: priority desc, created_at, ticket_id."""
    return (-ticket["priority"], ticket["created_at"], ticket["ticket_id"])


def ticket_cursor(ticket: Mapping[str, Any]) -> str:
    """The cursor of the page that starts after ``ticket``."""
    return encode_cursor([ticket["priority"], ticket["created_at"], ticket["ticket_id"]])


def decode_ticket_cursor(cursor: str | None) -> tuple[int, int, str] | None:
    """The (priority, created_at, ticket_id) of the last Ticket on the previous page."""
    return None if cursor is None else decode_cursor(cursor, (int, int, str))


def create_ticket(
    alert: Mapping[str, Any],
    *,
    origin: str,
    entities: Sequence[Mapping[str, Any]],
    handling_type: str = "other",
    specialist: str = "none",
    ticket_id: str | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Create and validate a new C6 Ticket from one C5 AlertRecord."""
    alert_record = _contract_dict("AlertRecord", alert)
    entity_records = [_contract_dict("Entity", entity) for entity in entities]
    target_asset = alert_record["dst_asset"] or alert_record["src_asset"]
    criticality = target_asset["criticality"] if target_asset is not None else 1
    created_at = _now_ms() if now_ms is None else now_ms
    ticket = {
        "ticket_id": _new_ticket_id() if ticket_id is None else ticket_id,
        "origin": origin,
        "status": "new",
        "handling_type": handling_type,
        "specialist": specialist,
        "priority": alert_record["severity_id"] * criticality,
        "alert_ids": [alert_record["alert_id"]],
        "entities": entity_records,
        "verdict": None,
        "extensions": {},
        "created_at": created_at,
        "updated_at": created_at,
        "awaiting_human_at": None,
    }
    return _contract_dict("Ticket", ticket)


def transition_ticket(
    ticket: Mapping[str, Any], new_status: str, *, now_ms: int | None = None
) -> dict[str, Any]:
    """Apply one allowed C6 v2 status transition, preserving all other fields."""
    current = _contract_dict("Ticket", ticket)
    old_status = current["status"]
    if new_status not in ALLOWED_TICKET_TRANSITIONS.get(old_status, frozenset()):
        raise InvalidTicketTransition(
            f"Ticket transition not allowed: {old_status} -> {new_status}"
        )
    updated = current | {
        "status": new_status,
        "updated_at": _now_ms() if now_ms is None else now_ms,
    }
    return _contract_dict("Ticket", updated)


def index_decided_ticket(ticket: Mapping[str, Any], sink: TicketVectorSink) -> None:
    """Pass a completed L1 result to the future vector index implementation."""
    validated = _contract_dict("Ticket", ticket)
    if validated["status"] not in DECIDED_TICKET_STATUSES:
        raise TicketNotDecidedError("Ticket decision is not complete")
    sink.add_decided_ticket(validated)


def open_ticket_store(settings: Any, environ=None, registry=None) -> TicketStore:
    """Open the configured Ticket store through the common store factory from issue #50."""
    from soc.store import open_store

    kwargs = {}
    if environ is not None:
        kwargs["environ"] = environ
    if registry is not None:
        kwargs["registry"] = registry
    return open_store("tickets", settings, **kwargs)


class TicketService:
    """Create, read, and transition C6 Tickets through a replaceable store."""

    def __init__(
        self,
        store: TicketStore,
        *,
        clock: Callable[[], int] = _now_ms,
        id_factory: Callable[[], str] = _new_ticket_id,
    ):
        self._store = store
        self._clock = clock
        self._id_factory = id_factory

    @classmethod
    def from_settings(cls, settings: Any, environ=None, registry=None) -> "TicketService":
        return cls(open_ticket_store(settings, environ=environ, registry=registry))

    def create(
        self,
        alert: Mapping[str, Any],
        *,
        origin: str,
        entities: Sequence[Mapping[str, Any]],
        handling_type: str = "other",
        specialist: str = "none",
    ) -> dict[str, Any]:
        ticket = create_ticket(
            alert,
            origin=origin,
            entities=entities,
            handling_type=handling_type,
            specialist=specialist,
            ticket_id=self._id_factory(),
            now_ms=self._clock(),
        )
        return _contract_dict("Ticket", self._store.create(ticket))

    def get(self, ticket_id: str) -> dict[str, Any] | None:
        ticket = self._store.get(ticket_id)
        return None if ticket is None else _contract_dict("Ticket", ticket)

    def find_by_entity(self, entity_type: str, entity_value: str) -> list[dict[str, Any]]:
        entity = _contract_dict("Entity", {"type": entity_type, "value": entity_value})
        tickets = self._store.find_by_entity(entity["type"], entity["value"])
        return [_contract_dict("Ticket", ticket) for ticket in tickets]

    def transition(self, ticket_id: str, new_status: str) -> dict[str, Any]:
        current = self.get(ticket_id)
        if current is None:
            raise TicketNotFoundError("Ticket not found")
        updated = transition_ticket(current, new_status, now_ms=self._clock())
        return _contract_dict(
            "Ticket",
            self._store.update(updated, expected_status=current["status"]),
        )

    def decide(
        self,
        ticket_id: str,
        new_status: str,
        verdict: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Save a final L1 status and its C7 Verdict in one expected-status update."""
        current = self.get(ticket_id)
        if current is None:
            raise TicketNotFoundError("Ticket not found")
        validated_verdict = _contract_dict("Verdict", verdict)
        updated = transition_ticket(current, new_status, now_ms=self._clock())
        updated["verdict"] = validated_verdict
        return _contract_dict(
            "Ticket",
            self._store.update(updated, expected_status=current["status"]),
        )

    def index_decided(self, ticket_id: str, sink: TicketVectorSink) -> None:
        ticket = self.get(ticket_id)
        if ticket is None:
            raise TicketNotFoundError("Ticket not found")
        index_decided_ticket(ticket, sink)

    def list(
        self,
        *,
        status: str | None = None,
        origin: str | None = None,
        handling_type: str | None = None,
        min_priority: int | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_LIMIT,
    ) -> TicketPage:
        """C6 in ``GET /api/tickets`` order (see ``TicketStore.list``)."""
        check_ticket_list_args(
            status=status,
            origin=origin,
            handling_type=handling_type,
            min_priority=min_priority,
            limit=limit,
        )
        decode_ticket_cursor(cursor)
        page = self._store.list(
            status=status,
            origin=origin,
            handling_type=handling_type,
            min_priority=min_priority,
            cursor=cursor,
            limit=limit,
        )
        items = [_contract_dict("Ticket", ticket) for ticket in page.items]
        return TicketPage(items, page.next_cursor)
