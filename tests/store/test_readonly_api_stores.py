"""Read-only Agent Log store and evidence queue for the screen API (box 27).

The screen API only reads, so it opens every store through the read-only
account ``database.readonly_url_env`` names (docs/security-policy.md 4). These
tests fail if a factory connects with the writable URL by mistake: with only
DATABASE_URL in the environment it must not open at all.
"""

import json
import os
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg import sql

from soc.config import MissingSecretError, load_config
from soc.contracts import validate_contract
from soc.db import apply_migrations, connect
from soc.l1.evidence import EVIDENCE_QUEUES, open_evidence_queue
from soc.l1.evidence.postgresql import PostgresEvidenceQueue
from soc.plugins import PluginRegistry
from soc.store import READONLY_AGENT_LOG, open_store
from soc.store.postgresql.agent_log import PostgresAgentLogStore

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
WRITABLE_ONLY = {"DATABASE_URL": "postgresql://localhost/zt"}


def load_json(*parts):
    return json.loads(FIXTURES.joinpath(*parts).read_text(encoding="utf-8"))


def test_readonly_agent_log_store_refuses_to_use_the_writable_url():
    settings = load_config(environ={})
    with pytest.raises(MissingSecretError, match="DATABASE_READONLY_URL"):
        open_store(READONLY_AGENT_LOG, settings, environ=WRITABLE_ONLY)


def test_readonly_evidence_queue_refuses_to_use_the_writable_url():
    settings = load_config(environ={})
    with pytest.raises(MissingSecretError, match="DATABASE_READONLY_URL"):
        open_evidence_queue(settings, environ=WRITABLE_ONLY, readonly=True)


def test_a_fake_queue_replaces_the_read_only_backend_by_registry():
    """A backend registers its read-only queue as ``<backend>.readonly``."""
    registry = PluginRegistry("evidence_queues")
    registry.register("postgresql.readonly", lambda settings, environ: "fake-readonly")
    registry.register("postgresql", lambda settings, environ: "fake-writable")
    settings = load_config(environ={})

    assert open_evidence_queue(settings, environ={}, registry=registry, readonly=True) == (
        "fake-readonly"
    )
    assert open_evidence_queue(settings, environ={}, registry=registry) == "fake-writable"


def test_the_repo_registers_a_read_only_queue_for_its_backend():
    assert EVIDENCE_QUEUES.get("postgresql.readonly") is not None


@pytest.mark.db
class TestReadonlyAgainstPostgres:
    @pytest.fixture
    def environ(self):
        environ = dict(os.environ)
        environ.setdefault("DATABASE_READONLY_URL", environ["DATABASE_URL"])
        return environ

    @pytest.fixture
    def schema(self):
        name = f"zt_test_{uuid.uuid4().hex[:12]}"
        with connect(load_config(environ=os.environ)) as connection:
            connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(name)))
            connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(name)))
            connection.commit()
            apply_migrations(connection)
            connection.commit()
        yield name
        with connect(load_config(environ=os.environ)) as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(name)))
            connection.commit()

    @pytest.fixture
    def opened(self, schema, environ):
        """Open a store through its factory and point it at the test schema."""
        stores = []

        def opener(kind):
            settings = load_config(environ=environ)
            store = (
                open_evidence_queue(settings, environ=environ, readonly=True)
                if kind == "queue"
                else open_store(kind, settings, environ=environ)
            )
            stores.append(store)
            # The factory owns the connection; the test only moves it to its schema.
            connection = store._connection
            connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            connection.commit()
            return store

        yield opener
        for store in stores:
            store.close()

    def writable(self, schema, environ):
        connection = connect(load_config(environ=environ), environ)
        connection.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        connection.commit()
        return connection

    def test_readonly_agent_log_reads_but_cannot_write(self, schema, environ, opened):
        step = validate_contract("AgentStep", load_json("agent_log", "agent_step.json"))
        with self.writable(schema, environ) as connection:
            PostgresAgentLogStore(connection).save_step(step)

        store = opened(READONLY_AGENT_LOG)
        entries = store.list_steps("alert", step.subject_id)
        assert [entry.step.step for entry in entries] == [1]
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            store.save_step(step)

    def test_readonly_queue_lists_but_cannot_enqueue(self, schema, environ, opened):
        request = load_json("l1", "evidence", "specialist_ticket_request.json")
        with self.writable(schema, environ) as connection:
            PostgresEvidenceQueue(connection).enqueue(request, agent="l1")

        queue = opened("queue")
        found = queue.list_by_requester("ticket", request["requester_id"])
        assert [item["request_id"] for item in found] == [request["request_id"]]
        with pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
            queue.enqueue({**request, "request_id": "rq_readonly_probe"}, agent="l1")
