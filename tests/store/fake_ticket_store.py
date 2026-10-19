"""In-memory Ticket store with list support. Passes the Ticket list contract tests."""

import copy

from soc.l1.tickets import (
    TicketPage,
    check_ticket_list_args,
    decode_ticket_cursor,
    ticket_cursor,
    ticket_sort_key,
)
from soc.store.paging import DEFAULT_PAGE_LIMIT


class FakeTicketStore:
    def __init__(self):
        self.tickets = {}

    def create(self, ticket):
        self.tickets[ticket["ticket_id"]] = copy.deepcopy(dict(ticket))
        return copy.deepcopy(self.tickets[ticket["ticket_id"]])

    def get(self, ticket_id):
        ticket = self.tickets.get(ticket_id)
        return None if ticket is None else copy.deepcopy(ticket)

    def find_by_entity(self, entity_type, entity_value):
        entity = {"type": entity_type, "value": entity_value}
        return [copy.deepcopy(t) for t in self.tickets.values() if entity in t["entities"]]

    def update(self, ticket, *, expected_status):
        self.tickets[ticket["ticket_id"]] = copy.deepcopy(dict(ticket))
        return copy.deepcopy(self.tickets[ticket["ticket_id"]])

    def list(self, *, status=None, origin=None, cursor=None, limit=DEFAULT_PAGE_LIMIT):
        check_ticket_list_args(status, origin, limit)
        after = decode_ticket_cursor(cursor)
        after_key = None if after is None else (-after[0], after[1], after[2])
        found = sorted(
            (
                t
                for t in self.tickets.values()
                if (status is None or t["status"] == status)
                and (origin is None or t["origin"] == origin)
                and (after_key is None or ticket_sort_key(t) > after_key)
            ),
            key=ticket_sort_key,
        )
        page = [copy.deepcopy(t) for t in found[:limit]]
        next_cursor = ticket_cursor(page[-1]) if len(found) > limit else None
        return TicketPage(page, next_cursor)


def fake_tickets_factory(settings, environ):
    return FakeTicketStore()
