import json
import os
import uuid
from pathlib import Path

import pytest
from psycopg import sql

from soc.config import load_config
from soc.contracts import ContractValidationError, validate_contract
from soc.db import apply_migrations, connect, discover_migrations
from soc.l1.agent_log import ArtifactReference, DuplicateAgentStepError
from soc.store.postgresql.agent_log import PostgresAgentLogStore

ROOT = Path(__file__).resolve().parents[2]
STEP_FIXTURE = ROOT / "tests/fixtures/agent_log/agent_step.json"
pytestmark = pytest.mark.db


@pytest.fixture
def connection():
    environ = os.environ
    if not environ.get("DATABASE_URL"):
        pytest.skip("DATABASE_URL is required for PostgreSQL integration tests")
    connection = connect(load_config(environ=environ), environ=environ)
    schema = f"zt_agent_log_{uuid.uuid4().hex[:12]}"
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


def load_step():
    return json.loads(STEP_FIXTURE.read_text(encoding="utf-8"))


def test_postgresql_agent_log_store_round_trips_c8_and_artifact_reference(connection):
    store = PostgresAgentLogStore(connection)
    step = validate_contract("AgentStep", load_step())
    artifact = ArtifactReference("a" * 64, "sha256/sample.txt")

    store.save_step(step, artifact)

    entries = store.list_steps(step.subject_type, step.subject_id)
    assert len(entries) == 1
    assert entries[0].step == step
    assert entries[0].artifact == artifact
    assert store.list_steps("alert", "al_missing") == []


def test_postgresql_agent_log_store_rejects_duplicate_subject_step(connection):
    store = PostgresAgentLogStore(connection)
    step = validate_contract("AgentStep", load_step())
    store.save_step(step)

    with pytest.raises(DuplicateAgentStepError):
        store.save_step(step)


def test_postgresql_agent_log_store_validates_c8_before_writing(connection):
    store = PostgresAgentLogStore(connection)
    step = load_step() | {"action": "unknown"}

    with pytest.raises(ContractValidationError):
        store.save_step(step)

    assert connection.execute("SELECT count(*) FROM agent_steps").fetchone() == (0,)


def test_agent_log_migration_uses_box_12_version_range(connection):
    versions = {migration.name: migration.version for migration in discover_migrations()}
    assert versions["create_agent_log"] == 30
    assert all(
        30 <= version <= 39 for name, version in versions.items() if name == "create_agent_log"
    )
    assert connection.execute("SELECT count(*) FROM agent_steps").fetchone() == (0,)
