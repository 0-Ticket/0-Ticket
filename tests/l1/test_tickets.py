import json
from pathlib import Path

import pytest

from soc.contracts import ContractValidationError, validate_contract
from soc.l1.tickets import (
    InvalidTicketTransition,
    TicketNotDecidedError,
    TicketService,
    create_ticket,
    index_decided_ticket,
    transition_ticket,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/tickets"


def load_fixture(name):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


ENTITIES = [{"type": "ip", "value": "203.0.113.10"}]


@pytest.mark.parametrize(
    ("alert_name", "expected_priority"),
    [
        ("alert_record_dst_asset.json", 20),
        ("alert_record_src_asset.json", 12),
        ("alert_record_no_assets.json", 2),
    ],
)
def test_create_ticket_uses_contract_priority_rule(alert_name, expected_priority):
    ticket = create_ticket(
        load_fixture(alert_name),
        origin="scenario",
        entities=ENTITIES,
        ticket_id="tk_priority_sample",
        now_ms=1791849600000,
    )

    assert ticket["priority"] == expected_priority
    assert ticket["alert_ids"] == [load_fixture(alert_name)["alert_id"]]
    assert ticket["status"] == "new"
    assert ticket["handling_type"] == "other"
    assert ticket["specialist"] == "none"
    assert ticket["awaiting_human_at"] is None
    assert validate_contract("Ticket", ticket).model_dump(mode="json") == ticket


@pytest.mark.parametrize("origin", ["l1_escalated", "l3_escalated", "scenario"])
def test_create_ticket_preserves_each_origin(origin):
    ticket = create_ticket(
        load_fixture("alert_record_dst_asset.json"),
        origin=origin,
        entities=ENTITIES,
        ticket_id="tk_origin_sample",
        now_ms=1791849600000,
    )

    assert ticket["origin"] == origin


def test_create_ticket_rejects_invalid_alert_record():
    alert = load_fixture("alert_record_dst_asset.json")
    del alert["severity_id"]

    with pytest.raises(ContractValidationError) as caught:
        create_ticket(
            alert,
            origin="scenario",
            entities=ENTITIES,
            ticket_id="tk_invalid_alert",
            now_ms=1791849600000,
        )

    assert caught.value.path == "/severity_id"


@pytest.mark.parametrize(
    ("old_status", "new_status"),
    [
        ("new", "triaging"),
        ("triaging", "on_hold"),
        ("triaging", "closed_benign"),
        ("triaging", "closed_fp"),
        ("triaging", "l2_escalated"),
    ],
)
def test_transition_ticket_accepts_only_documented_v2_edges(old_status, new_status):
    ticket = load_fixture("ticket.json")
    ticket["status"] = old_status

    transitioned = transition_ticket(ticket, new_status, now_ms=1791849601000)

    assert transitioned["status"] == new_status
    assert transitioned["updated_at"] == 1791849601000
    assert transitioned["awaiting_human_at"] is None
    assert validate_contract("Ticket", transitioned).model_dump(mode="json") == transitioned


@pytest.mark.parametrize(
    ("old_status", "new_status"),
    [
        ("new", "on_hold"),
        ("new", "closed_fp"),
        ("triaging", "awaiting_human"),
        ("triaging", "escalated"),
        ("on_hold", "triaging"),
        ("closed_fp", "triaging"),
        ("l2_escalated", "triaging"),
    ],
)
def test_transition_ticket_rejects_undocumented_edges(old_status, new_status):
    ticket = load_fixture("ticket.json")
    ticket["status"] = old_status

    with pytest.raises(InvalidTicketTransition):
        transition_ticket(ticket, new_status, now_ms=1791849601000)


def test_transition_ticket_preserves_an_existing_wait_timestamp():
    ticket = load_fixture("ticket.json")
    ticket["status"] = "triaging"
    ticket["awaiting_human_at"] = 1791849599000

    transitioned = transition_ticket(ticket, "closed_fp", now_ms=1791849601000)

    assert transitioned["awaiting_human_at"] == 1791849599000


class FakeTicketStore:
    def __init__(self):
        self.tickets = {}
        self.updates = []

    def create(self, ticket):
        self.tickets[ticket["ticket_id"]] = ticket
        return ticket

    def get(self, ticket_id):
        return self.tickets.get(ticket_id)

    def find_by_entity(self, entity_type, entity_value):
        return [
            ticket
            for ticket in self.tickets.values()
            if {"type": entity_type, "value": entity_value} in ticket["entities"]
        ]

    def update(self, ticket, expected_status):
        self.updates.append((ticket, expected_status))
        self.tickets[ticket["ticket_id"]] = ticket
        return ticket


def test_ticket_service_saves_and_queries_tickets_through_the_store_interface():
    store = FakeTicketStore()
    service = TicketService(store, clock=lambda: 1791849600000, id_factory=lambda: "tk_fake")

    created = service.create(
        load_fixture("alert_record_dst_asset.json"),
        origin="scenario",
        entities=ENTITIES,
    )

    assert created == store.get("tk_fake")
    assert service.find_by_entity("ip", "203.0.113.10") == [created]


def test_ticket_service_persists_only_valid_transitions():
    store = FakeTicketStore()
    ticket = load_fixture("ticket.json")
    store.create(ticket)
    service = TicketService(store, clock=lambda: 1791849601000)

    transitioned = service.transition(ticket["ticket_id"], "triaging")

    assert transitioned["status"] == "triaging"
    assert store.updates == [(transitioned, "new")]


def test_decided_ticket_vector_interface_rejects_unresolved_tickets():
    ticket = load_fixture("ticket.json")
    sink = FakeTicketVectorSink()

    with pytest.raises(TicketNotDecidedError):
        index_decided_ticket(ticket, sink)

    assert sink.tickets == []


@pytest.mark.parametrize("status", ["closed_benign", "closed_fp", "l2_escalated"])
def test_decided_ticket_vector_interface_accepts_final_l1_results(status):
    ticket = load_fixture("ticket.json")
    ticket["status"] = status
    sink = FakeTicketVectorSink()

    index_decided_ticket(ticket, sink)

    assert sink.tickets == [ticket]


class FakeTicketVectorSink:
    def __init__(self):
        self.tickets = []

    def add_decided_ticket(self, ticket):
        self.tickets.append(ticket)
