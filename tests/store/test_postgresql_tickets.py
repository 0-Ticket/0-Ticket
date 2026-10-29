import json
import os
import uuid
from pathlib import Path

import pytest
from psycopg import sql

from soc.config import load_config
from soc.contracts import ContractValidationError
from soc.db import apply_migrations, connect
from soc.l1.tickets import ConcurrentTicketUpdateError, TicketNotFoundError
from soc.store.postgresql.tickets import PostgresTicketStore

ROOT = Path(__file__).resolve().parents[2]
TICKET_FIXTURE = ROOT / "tests/fixtures/tickets/ticket.json"
pytestmark = pytest.mark.db


@pytest.fixture
def connection():
    environ = os.environ
    if not environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL is required for PostgreSQL integration tests")
    connection = connect(load_config(environ=environ), environ=environ)
    schema = f"zt_ticket_{uuid.uuid4().hex[:12]}"
    connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
    connection.commit()
    apply_migrations(connection)
    try:
        yield connection
    finally:
        connection.rollback()
        connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        connection.commit()


def load_ticket():
    return json.loads(TICKET_FIXTURE.read_text(encoding="utf-8"))


def test_ticket_store_creates_and_gets_contract_ticket(connection):
    store = PostgresTicketStore(connection)
    ticket = load_ticket()

    assert store.create(ticket) == ticket
    assert store.get(ticket["ticket_id"]) == ticket
    assert store.get("tk_missing") is None


@pytest.mark.parametrize("origin", ["l1_escalated", "l3_escalated", "scenario"])
def test_ticket_store_persists_each_contract_origin(connection, origin):
    store = PostgresTicketStore(connection)
    ticket = load_ticket() | {"ticket_id": f"tk_{origin}", "origin": origin}

    store.create(ticket)

    assert store.get(ticket["ticket_id"])["origin"] == origin


def test_ticket_store_finds_tickets_by_exact_entity_type_and_value(connection):
    store = PostgresTicketStore(connection)
    first = load_ticket()
    second = load_ticket() | {
        "ticket_id": "tk_other_entity",
        "entities": [{"type": "host", "value": "web-01"}],
    }
    store.create(first)
    store.create(second)

    assert store.find_by_entity("ip", "203.0.113.10") == [first]
    assert store.find_by_entity("host", "web-01") == [second]
    assert store.find_by_entity("ip", "web-01") == []


def test_ticket_store_updates_only_when_the_expected_status_matches(connection):
    store = PostgresTicketStore(connection)
    ticket = load_ticket()
    store.create(ticket)
    updated = ticket | {"status": "triaging", "updated_at": ticket["updated_at"] + 1}

    assert store.update(updated, expected_status="new") == updated
    assert store.get(ticket["ticket_id"]) == updated
    with pytest.raises(ConcurrentTicketUpdateError):
        store.update(ticket, expected_status="new")


def test_ticket_store_update_of_unknown_ticket_fails(connection):
    store = PostgresTicketStore(connection)
    ticket = load_ticket()

    with pytest.raises(TicketNotFoundError):
        store.update(ticket, expected_status="new")


def test_ticket_store_rejects_invalid_contract_before_writing(connection):
    store = PostgresTicketStore(connection)
    ticket = load_ticket()
    ticket["status"] = "awaiting_human"
    ticket.pop("awaiting_human_at")

    with pytest.raises(ContractValidationError):
        store.create(ticket)

    assert connection.execute("SELECT count(*) FROM tickets").fetchone() == (0,)


def test_migrations_apply_once_and_include_ticket_schema(connection):
    from soc.db import discover_migrations

    ticket_migrations = [
        migration for migration in discover_migrations() if migration.name == "create_tickets"
    ]
    assert [(migration.version, migration.name) for migration in ticket_migrations] == [
        (20, "create_tickets")
    ]
    assert [migration.version for migration in apply_migrations(connection)] == []
    assert connection.execute(
        "SELECT count(*) FROM schema_migrations WHERE version = 20"
    ).fetchone() == (1,)
    assert connection.execute("SELECT count(*) FROM tickets").fetchone() == (0,)
