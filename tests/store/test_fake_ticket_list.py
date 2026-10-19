"""The fake Ticket store passes the same list contract tests as PostgreSQL (box 10)."""

import pytest
from fake_ticket_store import FakeTicketStore
from ticket_list_contract import TicketListContract


class TestFakeTicketListContract(TicketListContract):
    @pytest.fixture
    def make_store(self):
        return FakeTicketStore
