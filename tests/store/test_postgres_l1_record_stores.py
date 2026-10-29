"""PostgreSQL C21, C23 and Ticket list stores (#69): the shared contracts plus read-only use.

Marked `db`: needs PostgreSQL through DATABASE_URL, and runs in CI against the
service container with `uv run pytest -m db`. Each test gets a fresh schema.
"""

import os
import uuid

import psycopg
import pytest
from branch_store_contract import BranchStoreContract, load_branches
from l1_decision_store_contract import L1DecisionStoreContract, load_decisions
from psycopg import sql
from readonly_schema import grant_readonly, readonly_environ
from ticket_list_contract import EXPECTED_ORDER, TicketListContract, load_ticket_list

from soc.config import load_config
from soc.db import apply_migrations, connect, connect_readonly
from soc.store.branches.postgres import PostgresBranchStore
from soc.store.l1_decisions.postgres import PostgresL1DecisionStore
from soc.store.postgresql.tickets import PostgresTicketStore

pytestmark = pytest.mark.db


@pytest.fixture
def schema():
    """A fresh schema with every migration applied, dropped afterwards."""
    name = f"zt_test_{uuid.uuid4().hex[:12]}"
    try:
        with connect(load_config(environ=os.environ)) as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(name)))
            connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(name)))
            connection.commit()
            apply_migrations(connection)
            connection.commit()
            grant_readonly(connection, name)
        yield name
    finally:
        with connect(load_config(environ=os.environ)) as connection:
            connection.execute(
                sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(name))
            )
            connection.commit()


def _open(schema, readonly=False):
    environ = readonly_environ()
    settings = load_config(environ=environ)
    conn = (connect_readonly if readonly else connect)(settings, environ)
    conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
    conn.commit()
    return conn


@pytest.fixture
def conns(schema):
    opened = []

    def make(readonly=False):
        conn = _open(schema, readonly)
        opened.append(conn)
        return conn

    yield make
    for conn in opened:
        conn.close()


class TestPostgresBranchStoreContract(BranchStoreContract):
    @pytest.fixture
    def make_store(self, conns):
        return lambda: PostgresBranchStore(conns())


class TestPostgresL1DecisionStoreContract(L1DecisionStoreContract):
    @pytest.fixture
    def make_store(self, conns):
        return lambda: PostgresL1DecisionStore(conns())


class TestPostgresTicketListContract(TicketListContract):
    @pytest.fixture
    def make_store(self, conns):
        return lambda: PostgresTicketStore(conns())


def test_ticket_id_ties_use_code_point_order(conns):
    """Python string order, not the database's locale order, breaks the last tie."""
    store = PostgresTicketStore(conns())
    base = load_ticket_list()[0]
    for ticket_id in ("tk_b", "tk_B", "tk_a", "tk_A", "tk__"):
        store.create(base | {"ticket_id": ticket_id})
    listed = [t["ticket_id"] for t in store.list().items]
    assert listed == sorted(["tk_b", "tk_B", "tk_a", "tk_A", "tk__"])
    paged = []
    cursor = None
    while True:
        page = store.list(cursor=cursor, limit=2)
        paged += [t["ticket_id"] for t in page.items]
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    assert paged == listed


def test_readonly_connection_reads_c21_c23_and_ticket_list(conns):
    branches, decisions, tickets = (
        PostgresBranchStore(conns()),
        PostgresL1DecisionStore(conns()),
        PostgresTicketStore(conns()),
    )
    for item in load_branches():
        branches.save(item)
    for item in load_decisions():
        decisions.save(item)
    for ticket in load_ticket_list():
        tickets.create(ticket)

    ro_branches = PostgresBranchStore(conns(readonly=True))
    ro_decisions = PostgresL1DecisionStore(conns(readonly=True))
    ro_tickets = PostgresTicketStore(conns(readonly=True))

    first = load_branches()[0]
    assert ro_branches.get("alert", first.subject_id) == first
    assert len(ro_branches.list_by_path("l1_entity_lookup", None, 10)) == 2
    assert ro_decisions.get("alert", "al_sample_wpscan").decision == "held"
    assert len(ro_decisions.list(limit=2).items) == 2
    assert [t["ticket_id"] for t in ro_tickets.list().items] == EXPECTED_ORDER


def test_readonly_connection_cannot_write(conns):
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        PostgresBranchStore(conns(readonly=True)).save(load_branches()[0])
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        PostgresL1DecisionStore(conns(readonly=True)).save(load_decisions()[0])
    with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        PostgresTicketStore(conns(readonly=True)).create(load_ticket_list()[0])
