"""Test doubles for the evidence request queue (box 26).

``FakeEvidenceQueue`` keeps requests in memory in arrival order and follows the
same rules as the PostgreSQL queue, so both run the shared contract tests in
``evidence_queue_contract.py``. ``FakeTicketStore`` stands in for box 10's store.
"""

import copy
import json
from pathlib import Path

from soc.config import load_config
from soc.contracts import validate_contract
from soc.l1.evidence.base import (
    ClaimedRequest,
    DuplicateRequestError,
    RequestNotFoundError,
    RequestStateError,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests" / "fixtures" / "l1" / "evidence"
TICKET_FIXTURE = ROOT / "tests" / "fixtures" / "tickets" / "ticket.json"
AGENT = "l1"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def load_ticket(**changes) -> dict:
    return json.loads(TICKET_FIXTURE.read_text(encoding="utf-8")) | changes


def default_settings():
    return load_config(environ={})


def _request(value) -> dict:
    return validate_contract("EvidenceRequest", copy.deepcopy(dict(value))).model_dump(mode="json")


class FakeEvidenceQueue:
    def __init__(self):
        self._rows: dict[str, dict] = {}  # Insertion order is arrival order.
        self.closed = False

    def enqueue(self, request, *, agent):
        validated = _request(request)
        if validated["request_id"] in self._rows:
            raise DuplicateRequestError("request already queued")
        self._rows[validated["request_id"]] = {"agent": agent, "request": validated}
        return copy.deepcopy(validated)

    def claim_next(self, *, now_ms):
        for row in self._rows.values():
            if row["request"]["status"] == "pending":
                row["request"] = row["request"] | {"status": "in_progress", "updated_at": now_ms}
                return ClaimedRequest(copy.deepcopy(row["request"]), row["agent"])
        return None

    def update(self, request, *, expected_status):
        validated = _request(request)
        row = self._rows.get(validated["request_id"])
        if row is None:
            raise RequestNotFoundError("request not found")
        if row["request"]["status"] != expected_status:
            raise RequestStateError("request status changed before update")
        row["request"] = validated
        return copy.deepcopy(validated)

    def release_in_progress(self, *, now_ms):
        released = 0
        for row in self._rows.values():
            if row["request"]["status"] == "in_progress":
                row["request"] = row["request"] | {"status": "pending", "updated_at": now_ms}
                released += 1
        return released

    def get(self, request_id):
        row = self._rows.get(request_id)
        return None if row is None else copy.deepcopy(row["request"])

    def list_by_requester(self, requester_type, requester_id):
        return [
            copy.deepcopy(row["request"])
            for row in self._rows.values()
            if row["request"]["requester_type"] == requester_type
            and row["request"]["requester_id"] == requester_id
        ]

    def close(self):
        self.closed = True


class FakeTicketStore:
    def __init__(self, *tickets):
        self.tickets = {ticket["ticket_id"]: copy.deepcopy(ticket) for ticket in tickets}

    def create(self, ticket):
        self.tickets[ticket["ticket_id"]] = copy.deepcopy(dict(ticket))
        return copy.deepcopy(dict(ticket))

    def get(self, ticket_id):
        ticket = self.tickets.get(ticket_id)
        return None if ticket is None else copy.deepcopy(ticket)

    def find_by_entity(self, entity_type, entity_value):
        return []

    def update(self, ticket, *, expected_status):
        assert self.tickets[ticket["ticket_id"]]["status"] == expected_status
        self.tickets[ticket["ticket_id"]] = copy.deepcopy(dict(ticket))
        return copy.deepcopy(dict(ticket))
