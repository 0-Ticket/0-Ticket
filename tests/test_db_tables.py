"""공통 테이블과 마이그레이션 실행기를 실제 PostgreSQL로 확인한다(db 마커)."""

from pathlib import Path
from typing import Any

import psycopg
import pytest
from contract_samples import load, load_schema
from psycopg import sql
from psycopg.types.json import Jsonb

from soc.contracts import to_datetime, to_epoch_ms, validate_contract
from soc.db.migrate import MigrationError, migrate

pytestmark = pytest.mark.db

# 계약 이름 → 테이블. 외래 키 때문에 이 순서로 넣는다.
TABLES = {
    "raw_record": "raw_records",
    "alert": "alerts",
    "event": "events",
    "ticket": "tickets",
    "incident": "incidents",
    "case": "cases",
    "agent_log": "agent_logs",
}

Columns = dict[str, tuple[str, bool]]  # 컬럼 이름 → (자료형, null 가능)


@pytest.fixture
def migrated(temp_database: str) -> str:
    migrate(temp_database)
    return temp_database


def table_names(conn: psycopg.Connection) -> set[str]:
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'"
    ).fetchall()
    return {row[0] for row in rows}


def columns_of(conn: psycopg.Connection, table: str) -> Columns:
    rows = conn.execute(
        "SELECT column_name, data_type, is_nullable FROM information_schema.columns"
        " WHERE table_schema = 'public' AND table_name = %s",
        (table,),
    ).fetchall()
    return {name: (data_type, nullable == "YES") for name, data_type, nullable in rows}


def to_row(columns: Columns, data: dict[str, Any]) -> dict[str, Any]:
    row = {}
    for name, (data_type, nullable) in columns.items():
        value = data[name]
        if data_type == "timestamp with time zone" and value is not None:
            value = to_datetime(value)
        elif data_type == "jsonb" and not (value is None and nullable):
            value = Jsonb(value)
        row[name] = value
    return row


def from_row(columns: Columns, row: dict[str, Any]) -> dict[str, Any]:
    data = {}
    for name, (data_type, _) in columns.items():
        value = row[name]
        if data_type == "timestamp with time zone" and value is not None:
            value = to_epoch_ms(value)
        data[name] = value
    return data


def insert(conn: psycopg.Connection, table: str, data: dict[str, Any], *, skip_existing=False):
    columns = columns_of(conn, table)
    row = to_row(columns, data)
    query = sql.SQL("INSERT INTO {} ({}) VALUES ({}){}").format(
        sql.Identifier(table),
        sql.SQL(", ").join(map(sql.Identifier, row)),
        sql.SQL(", ").join(sql.Placeholder() * len(row)),
        sql.SQL(" ON CONFLICT DO NOTHING" if skip_existing else ""),
    )
    conn.execute(query, list(row.values()))


def select(conn: psycopg.Connection, table: str, row_id: str) -> dict[str, Any]:
    columns = columns_of(conn, table)
    query = sql.SQL("SELECT {} FROM {} WHERE id = %s").format(
        sql.SQL(", ").join(map(sql.Identifier, columns)), sql.Identifier(table)
    )
    values = conn.execute(query, (row_id,)).fetchone()
    assert values is not None
    return from_row(columns, dict(zip(columns, values, strict=True)))


def ensure_raw_record(conn: psycopg.Connection, raw_id: str, kind: str) -> None:
    """Alert·Event가 가리키는 원본이 샘플에 없으면 외래 키를 위해 만든다."""
    raw = {
        "id": raw_id,
        "kind": kind,
        "siem_profile": "test",
        "siem_ref": raw_id,
        "fetched_at": 1793678580000,
        "original": {},
    }
    validate_contract("raw_record", raw)
    insert(conn, "raw_records", raw, skip_existing=True)


def test_migrate_creates_all_tables_on_empty_db(temp_database: str) -> None:
    applied = migrate(temp_database)

    assert applied == ["0001_common_tables.sql"]
    with psycopg.connect(temp_database) as conn:
        assert table_names(conn) == {*TABLES.values(), "schema_migrations"}


def test_migrate_twice_does_not_reapply(temp_database: str) -> None:
    migrate(temp_database)

    applied = migrate(temp_database)

    assert applied == []
    with psycopg.connect(temp_database) as conn:
        assert conn.execute("SELECT count(*) FROM schema_migrations").fetchone() == (1,)


def test_failed_migration_rolls_back_only_that_file(temp_database: str, tmp_path: Path) -> None:
    (tmp_path / "0001_first.sql").write_text("CREATE TABLE first_table (id int);")
    (tmp_path / "0002_broken.sql").write_text(
        "CREATE TABLE broken_table (id int);\nSELECT * FROM missing_table;"
    )
    (tmp_path / "0003_third.sql").write_text("CREATE TABLE third_table (id int);")

    with pytest.raises(MigrationError, match="0002_broken.sql"):
        migrate(temp_database, tmp_path)

    with psycopg.connect(temp_database) as conn:
        assert table_names(conn) == {"first_table", "schema_migrations"}
        versions = conn.execute("SELECT version FROM schema_migrations").fetchall()
        assert versions == [(1,)]


def test_same_siem_document_is_rejected(migrated: str) -> None:
    first = load("valid", "raw_record")[0]["data"]
    second = {**first, "id": "raw_01a19f93-1150-7000-8000-0000000000ff"}

    with psycopg.connect(migrated) as conn:
        insert(conn, "raw_records", first)
        with pytest.raises(psycopg.errors.UniqueViolation):
            insert(conn, "raw_records", second)


def test_valid_samples_fit_tables_and_read_back(migrated: str) -> None:
    with psycopg.connect(migrated) as conn:
        for name, table in TABLES.items():
            for sample in load("valid", name):
                data = validate_contract(name, sample["data"]).model_dump(mode="json")
                if name in ("alert", "event"):
                    ensure_raw_record(conn, data["raw_id"], name)

                insert(conn, table, data)

                assert select(conn, table, data["id"]) == data, f"{name}-{sample['case']}"


@pytest.mark.parametrize(("name", "table"), TABLES.items())
def test_table_columns_match_contract_fields(migrated: str, name: str, table: str) -> None:
    schema = load_schema(f"{name}.schema.json")

    with psycopg.connect(migrated) as conn:
        assert set(columns_of(conn, table)) == set(schema["properties"])


@pytest.mark.parametrize(
    ("name", "field", "value"),
    [
        ("ticket", "status", "open"),
        ("ticket", "origin", "manual"),
        ("alert", "severity", 7),
        ("alert", "triage", {"status": "closed", "verdict": None}),
        ("incident", "status", "closed"),
        ("incident", "analysis_round", -1),
        ("case", "status", "closed"),
        ("agent_log", "seq", 0),
        ("agent_log", "outcome", "timeout"),
        ("raw_record", "kind", "log"),
        ("event", "ocsf_class", -1),
    ],
)
def test_check_constraints_reject_values_outside_contract(
    migrated: str, name: str, field: str, value: Any
) -> None:
    data = {**load("valid", name)[0]["data"], field: value}

    with psycopg.connect(migrated) as conn:
        if name in ("alert", "event"):
            ensure_raw_record(conn, data["raw_id"], name)
        if name == "case":
            insert(conn, "incidents", load("valid", "incident")[3]["data"])
        with pytest.raises(psycopg.errors.CheckViolation):
            insert(conn, TABLES[name], data)
