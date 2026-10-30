"""PostgreSQL evidence queue (unnumbered, D-034): the shared contract plus table rules.

Marked `db`: needs PostgreSQL through DATABASE_URL (`docker compose up -d`), and
runs in CI against the service container with `uv run pytest -m db`.
"""

import os
import uuid

import psycopg
import pytest
from evidence_fakes import AGENT, load
from evidence_queue_contract import EvidenceQueueContract
from psycopg import sql

from soc.config import load_config
from soc.db import apply_migrations, connect
from soc.l1.evidence.postgresql import PostgresEvidenceQueue

pytestmark = pytest.mark.db


@pytest.fixture
def schema():
    """A fresh schema with every migration applied, dropped afterwards."""
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL is required for PostgreSQL integration tests")
    name = f"zt_evidence_{uuid.uuid4().hex[:12]}"
    with connect(load_config(environ=os.environ)) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(name)))
        admin.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(name)))
        admin.commit()
        apply_migrations(admin)
        try:
            yield name
        finally:
            admin.rollback()
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(name)))
            admin.commit()


@pytest.fixture
def make_connection(schema):
    opened = []

    def make():
        connection = connect(load_config(environ=os.environ))
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        connection.commit()
        opened.append(connection)
        return connection

    yield make
    for connection in opened:
        connection.close()


class TestPostgresEvidenceQueueContract(EvidenceQueueContract):
    @pytest.fixture
    def make_queue(self, make_connection):
        # Each queue gets its own connection, as two workers would.
        return lambda: PostgresEvidenceQueue(make_connection())


def test_queue_migrations_use_only_0040_to_0049():
    from soc.db import discover_migrations

    versions = [m.version for m in discover_migrations() if "evidence" in m.name]
    assert versions == [40]
    assert all(40 <= version < 50 for version in versions)


def test_status_column_must_match_the_payload(make_connection):
    connection = make_connection()
    queue = PostgresEvidenceQueue(connection)
    request = queue.enqueue(load("siem_mcp_alert_request.json"), agent=AGENT)

    with pytest.raises(psycopg.errors.CheckViolation), connection.transaction():
        connection.execute(
            "UPDATE evidence_requests SET status = 'failed' WHERE request_id = %s",
            (request["request_id"],),
        )
    assert queue.get(request["request_id"]) == request


def test_claim_skips_a_row_another_worker_holds(make_connection):
    holder = make_connection()
    worker = PostgresEvidenceQueue(make_connection())
    worker.enqueue(load("siem_mcp_alert_request.json"), agent=AGENT)
    worker.enqueue(load("lookup_ticket_request.json"), agent=AGENT)

    with holder.transaction():
        holder.execute(
            "SELECT 1 FROM evidence_requests WHERE request_id = %s FOR UPDATE",
            ("rq_siem_alert_sample",),
        )
        claimed = worker.claim_next(now_ms=1)

    assert claimed.request["request_id"] == "rq_lookup_sample"
