"""Shared contract tests for ``TicketStore.list`` (box 10, ``GET /api/tickets`` order).

Subclass ``TicketListContract`` in a ``Test*`` class and provide ``make_store``:
a function returning a fresh, empty Ticket store.
"""

import json
from pathlib import Path

import pytest

from soc.l1.tickets import TicketPage

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"

# priority desc, then created_at, then ticket_id (docs/api-contracts.md).
EXPECTED_ORDER = ["tk_list_c", "tk_list_a", "tk_list_b", "tk_list_e", "tk_list_d"]


def load_ticket_list():
    return json.loads((FIXTURES / "tickets" / "ticket_list.json").read_text(encoding="utf-8"))


def ids(page):
    return [ticket["ticket_id"] for ticket in page.items]


def walk(store, limit, **filters):
    seen, cursor = [], None
    while True:
        page = store.list(cursor=cursor, limit=limit, **filters)
        seen += ids(page)
        if page.next_cursor is None:
            return seen
        cursor = page.next_cursor


class TicketListContract:
    @pytest.fixture
    def filled(self, make_store):
        store = make_store()
        # Saved out of order so the order cannot come from insertion.
        for ticket in reversed(load_ticket_list()):
            store.create(ticket)
        return store

    def test_list_is_in_api_order(self, filled):
        page = filled.list()
        assert isinstance(page, TicketPage)
        assert ids(page) == EXPECTED_ORDER
        assert page.next_cursor is None
        assert page.items[0] == next(t for t in load_ticket_list() if t["ticket_id"] == "tk_list_c")

    def test_empty_store_lists_nothing(self, make_store):
        page = make_store().list()
        assert page.items == [] and page.next_cursor is None

    @pytest.mark.parametrize(
        ("filters", "expected"),
        [
            ({"status": "new"}, ["tk_list_c", "tk_list_a", "tk_list_e"]),
            ({"origin": "scenario"}, ["tk_list_a", "tk_list_d"]),
            ({"status": "new", "origin": "l1_escalated"}, ["tk_list_c"]),
            ({"status": "l2_escalated"}, []),
            ({"handling_type": "web_attack"}, ["tk_list_c", "tk_list_a"]),
            # A plugin-registered value is a filter value like any other.
            ({"handling_type": "example.custom"}, ["tk_list_e"]),
            ({"handling_type": "cloud"}, []),
            ({"min_priority": 15}, ["tk_list_c", "tk_list_a", "tk_list_b", "tk_list_e"]),
            ({"min_priority": 25}, ["tk_list_c", "tk_list_a", "tk_list_b"]),
            ({"min_priority": 0}, EXPECTED_ORDER),
            ({"min_priority": 26}, []),
            ({"handling_type": "web_attack", "min_priority": 25}, ["tk_list_c", "tk_list_a"]),
            ({"status": "new", "min_priority": 20}, ["tk_list_c", "tk_list_a"]),
        ],
    )
    def test_list_filters(self, filled, filters, expected):
        assert ids(filled.list(**filters)) == expected

    @pytest.mark.parametrize(
        ("filters", "expected"),
        [
            ({"min_priority": 15}, ["tk_list_c", "tk_list_a", "tk_list_b", "tk_list_e"]),
            ({"handling_type": "web_attack"}, ["tk_list_c", "tk_list_a"]),
        ],
    )
    def test_filters_apply_before_paging(self, filled, filters, expected):
        # Filtering a page after reading it would leave gaps and empty pages.
        assert walk(filled, 1, **filters) == expected
        assert walk(filled, 2, **filters) == expected

    @pytest.mark.parametrize("limit", [1, 2, 4])
    def test_pages_have_no_gaps_or_repeats(self, filled, limit):
        assert walk(filled, limit) == EXPECTED_ORDER

    def test_paged_filter_keeps_the_order(self, filled):
        assert walk(filled, 1, status="new") == ["tk_list_c", "tk_list_a", "tk_list_e"]

    def test_last_full_page_has_no_cursor(self, filled):
        assert filled.list(limit=5).next_cursor is None
        assert filled.list(limit=4).next_cursor is not None

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"status": "done"},
            {"origin": "manual"},
            {"handling_type": ""},
            {"min_priority": -1},
            {"min_priority": 1.5},
            {"min_priority": "15"},
            {"min_priority": True},
            {"limit": 0},
            {"limit": 201},
            {"cursor": "%%%"},
            {"cursor": "WyJ4Il0="},  # ["x"]: valid base64 JSON, wrong shape
        ],
    )
    def test_list_rejects_bad_arguments(self, make_store, kwargs):
        with pytest.raises(ValueError):
            make_store().list(**kwargs)
