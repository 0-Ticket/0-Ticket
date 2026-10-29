"""Writes made after a read on the same connection survive close (#83).

The runners (box 25, box 11) share one connection across several stores, so a
store write often follows a read on that connection, for example `tickets.get`
before `create`. Without autocommit that read opens a transaction, the write's
`transaction()` becomes a savepoint, and close rolls everything back.

Each test reads on the connection (a plain SELECT, as another store would, plus
the store's own read), writes, closes, then reads the value back on a new
connection. Reading back on the writing connection would hide the bug.

Marked `db`: needs PostgreSQL through DATABASE_URL (`uv run pytest -m db`).
"""

import json
import os
import uuid
from pathlib import Path

import pytest
from psycopg import sql

from soc.config import load_config
from soc.contracts import validate_contract
from soc.db import apply_migrations, connect
from soc.ingest.connector import source_record_id
from soc.l1.evidence.postgresql import PostgresEvidenceQueue
from soc.store.branches.postgres import PostgresBranchStore
from soc.store.l1_decisions.postgres import PostgresL1DecisionStore
from soc.store.lookups.postgres import PostgresLookupStore
from soc.store.postgresql.agent_log import PostgresAgentLogStore
from soc.store.postgresql.tickets import PostgresTicketStore
from soc.store.records.postgres import PostgresRecordStore

pytestmark = pytest.mark.db

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
NOW = 1791849600000


def _json(path: str):
    return json.loads((FIXTURES / path).read_text(encoding="utf-8"))


@pytest.fixture
def schema():
    """A fresh schema with every migration applied, dropped afterwards."""
    if not os.environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL is required for PostgreSQL integration tests")
    name = f"zt_commit_{uuid.uuid4().hex[:12]}"
    with connect(load_config(environ=os.environ)) as admin:
        admin.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(name)))
        admin.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(name)))
        admin.commit()
        apply_migrations(admin)
        admin.commit()
    try:
        yield name
    finally:
        with connect(load_config(environ=os.environ)) as admin:
            admin.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(name)))
            admin.commit()


@pytest.fixture
def open_conn(schema):
    """Open a new connection on the test schema, the way a command does."""
    opened = []

    def make():
        conn = connect(load_config(environ=os.environ))
        conn.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        conn.commit()
        opened.append(conn)
        return conn

    yield make
    for conn in opened:
        conn.close()


def read_first(conn):
    """A read another store makes on the shared connection before the write."""
    assert conn.execute("SELECT 1").fetchone() == (1,)


def test_ticket_create_after_read_survives_close(open_conn):
    conn = open_conn()
    ticket = _json("tickets/ticket.json")
    store = PostgresTicketStore(conn)
    read_first(conn)
    assert store.get(ticket["ticket_id"]) is None

    store.create(ticket)
    conn.close()

    assert PostgresTicketStore(open_conn()).get(ticket["ticket_id"]) == ticket


def test_ticket_update_after_read_survives_close(open_conn):
    ticket = _json("tickets/ticket.json")
    PostgresTicketStore(open_conn()).create(ticket)
    conn = open_conn()
    store = PostgresTicketStore(conn)
    read_first(conn)
    current = store.get(ticket["ticket_id"])
    updated = current | {"status": "triaging", "updated_at": current["updated_at"] + 1}

    store.update(updated, expected_status="new")
    conn.close()

    assert PostgresTicketStore(open_conn()).get(ticket["ticket_id"]) == updated


def test_agent_step_after_read_survives_close(open_conn):
    conn = open_conn()
    step = validate_contract("AgentStep", _json("agent_log/agent_step.json"))
    store = PostgresAgentLogStore(conn)
    read_first(conn)
    assert store.list_steps(step.subject_type, step.subject_id) == []

    store.save_step(step)
    conn.close()

    entries = PostgresAgentLogStore(open_conn()).list_steps(step.subject_type, step.subject_id)
    assert [entry.step for entry in entries] == [step]


def test_branch_after_read_survives_close(open_conn):
    conn = open_conn()
    branch = validate_contract("BranchResult", _json("branches/branch_results.json")[0])
    store = PostgresBranchStore(conn)
    read_first(conn)
    assert store.get(branch.subject_type, branch.subject_id) is None

    store.save(branch)
    conn.close()

    saved = PostgresBranchStore(open_conn()).get(branch.subject_type, branch.subject_id)
    assert saved == branch


def test_l1_decision_after_read_survives_close(open_conn):
    conn = open_conn()
    decision = validate_contract("L1DecisionRecord", _json("l1_decisions/l1_decisions.json")[0])
    store = PostgresL1DecisionStore(conn)
    read_first(conn)
    assert store.get(decision.subject_type, decision.subject_id) is None

    store.save(decision)
    conn.close()

    saved = PostgresL1DecisionStore(open_conn()).get(decision.subject_type, decision.subject_id)
    assert saved == decision


def _stored_alert_pair(records):
    """Store two copies of a sample C5 alert, each with its own C2 source."""
    sample = _json("store/alert_records.json")[0]
    alerts = []
    for alert_id in ("al_commit_target", "al_commit_duplicate"):
        content = {"kind": "alert", "scenario": "commit_test", "raw_ids": [], "fields": {}}
        content["fields"]["alert"] = alert_id
        source = validate_contract(
            "SiemAlert", {**content, "source_record_id": source_record_id(content)}
        )
        records.save_source_records([source], "test", None)
        alert = validate_contract(
            "AlertRecord",
            {**sample, "alert_id": alert_id, "source_record_id": source.source_record_id},
        )
        records.save_alert_record(alert)
        alerts.append(alert)
    return alerts


def test_merge_duplicate_after_read_survives_close(open_conn):
    target, duplicate = _stored_alert_pair(PostgresRecordStore(open_conn(), 0, lambda: NOW))
    conn = open_conn()
    records = PostgresRecordStore(conn, 0, lambda: NOW)
    read_first(conn)
    assert records.get_alert_record(target.alert_id).count == target.count

    assert records.merge_duplicate(target.alert_id, duplicate.alert_id, target.last_seen) is True
    conn.close()

    reopened = PostgresRecordStore(open_conn(), 0, lambda: NOW)
    assert reopened.get_alert_record(target.alert_id).count == target.count + 1


def test_evidence_request_after_read_survives_close(open_conn):
    conn = open_conn()
    request = _json("l1/evidence/siem_mcp_alert_request.json")
    queue = PostgresEvidenceQueue(conn)
    read_first(conn)
    assert queue.get(request["request_id"]) is None

    queued = queue.enqueue(request, agent="l1")
    conn.close()

    assert PostgresEvidenceQueue(open_conn()).get(queued["request_id"]) == queued


def test_lookup_replace_after_read_survives_close(open_conn):
    conn = open_conn()
    row = validate_contract(
        "AssetInfo",
        {
            "match": "192.0.2.80",
            "hostname": "web-01",
            "criticality": 5,
            "owner": None,
            "zone": None,
            "shared": False,
            "valid_from": None,
            "valid_to": None,
            "extensions": {},
        },
    )
    store = PostgresLookupStore(conn)
    read_first(conn)
    assert store.asset_candidates("192.0.2.80", NOW) == []

    store.replace_assets([row])
    conn.close()

    assert PostgresLookupStore(open_conn()).asset_candidates("192.0.2.80", NOW) == [row]
