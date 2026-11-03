"""공통 테이블과 마이그레이션 실행기를 실제 PostgreSQL로 확인한다(db 마커)."""

from datetime import timedelta
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


def insert(
    conn: psycopg.Connection,
    table: str,
    data: dict[str, Any],
    *,
    skip_existing: bool = False,
    raw: dict[str, Any] | None = None,
) -> None:
    """data를 컬럼 형식으로 바꿔 넣는다. raw에 준 값은 바꾸지 않고 그대로 넣는다."""
    columns = columns_of(conn, table)
    row = {**to_row(columns, data), **(raw or {})}
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


def ensure_parents(conn: psycopg.Connection, name: str, data: dict[str, Any]) -> None:
    """외래 키가 가리키는 행(Alert·Event의 원본, Case의 Incident)을 먼저 넣는다."""
    if name in ("alert", "event"):
        ensure_raw_record(conn, data["raw_id"], name)
    if name == "case":
        incidents = [s["data"] for s in load("valid", "incident")]
        incident = next(i for i in incidents if i["id"] == data["incident_id"])
        insert(conn, "incidents", incident, skip_existing=True)


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


def test_migrate_stops_when_applied_file_was_renamed(temp_database: str, tmp_path: Path) -> None:
    (tmp_path / "0001_first.sql").write_text("CREATE TABLE first_table (id int);")
    migrate(temp_database, tmp_path)
    (tmp_path / "0001_first.sql").rename(tmp_path / "0001_renamed.sql")
    (tmp_path / "0002_second.sql").write_text("CREATE TABLE second_table (id int);")

    with pytest.raises(MigrationError, match="0001_first.sql.*0001_renamed.sql"):
        migrate(temp_database, tmp_path)

    with psycopg.connect(temp_database) as conn:
        assert table_names(conn) == {"first_table", "schema_migrations"}  # 0002도 돌리지 않는다


@pytest.mark.parametrize("table", ["alerts", "events"])
def test_raw_id_is_indexed(migrated: str, table: str) -> None:
    with psycopg.connect(migrated) as conn:
        definitions = [
            row[0]
            for row in conn.execute(
                "SELECT indexdef FROM pg_indexes WHERE schemaname = 'public' AND tablename = %s",
                (table,),
            )
        ]

    assert any(d.endswith("(raw_id)") for d in definitions), definitions


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
        ensure_parents(conn, name, data)
        with pytest.raises(psycopg.errors.CheckViolation):
            insert(conn, TABLES[name], data)


@pytest.mark.parametrize(
    ("time_zone", "offset"),
    [("Pacific/Kiritimati", timedelta(hours=14)), ("Asia/Seoul", timedelta(hours=9))],
)
def test_upper_bound_time_reads_back_in_non_utc_session(
    migrated: str, time_zone: str, offset: timedelta
) -> None:
    """psycopg는 timestamptz를 세션 시간대로 돌려준다.

    상한 시각도 가장 큰 오프셋(+14h)에서 읽혀야 한다.
    """
    samples = load("valid", "agent_log")
    sample = next(s["data"] for s in samples if s["case"] == "limits_at_upper_bounds")
    data = validate_contract("agent_log", sample).model_dump(mode="json")

    with psycopg.connect(migrated, options=f"-c TimeZone={time_zone}") as conn:
        assert conn.execute("SHOW TimeZone").fetchone() == (time_zone,)
        insert(conn, "agent_logs", data)

        started_at = conn.execute(
            "SELECT started_at FROM agent_logs WHERE id = %s", (data["id"],)
        ).fetchone()[0]
        assert started_at.utcoffset() == offset  # 세션 시간대로 바뀌어 돌아온다
        assert select(conn, "agent_logs", data["id"]) == data


def test_jsonb_columns_reject_json_null(migrated: str) -> None:
    """JSON null('null'::jsonb)은 NOT NULL과 IS NULL 조회를 피해 가므로 DB가 거부한다."""
    checked = []
    with psycopg.connect(migrated) as conn:
        for name, table in TABLES.items():
            data = load("valid", name)[0]["data"]
            ensure_parents(conn, name, data)
            for column, (data_type, _) in columns_of(conn, table).items():
                if data_type != "jsonb" or (table, column) == ("agent_logs", "input"):
                    continue
                with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
                    insert(conn, table, data, raw={column: Jsonb(None)})
                checked.append(f"{table}.{column}")

    assert len(checked) == 19, checked  # jsonb 컬럼 20개 중 agent_logs.input만 뺀다


@pytest.mark.parametrize(
    ("name", "column"), [("alert", "triage"), ("ticket", "verdict"), ("agent_log", "output")]
)
def test_nullable_jsonb_columns_take_sql_null(migrated: str, name: str, column: str) -> None:
    data = {**load("valid", name)[0]["data"], column: None}

    with psycopg.connect(migrated) as conn:
        ensure_parents(conn, name, data)
        insert(conn, TABLES[name], data)

        query = sql.SQL("SELECT {} IS NULL FROM {} WHERE id = %s").format(
            sql.Identifier(column), sql.Identifier(TABLES[name])
        )
        assert conn.execute(query, (data["id"],)).fetchone() == (True,)


def test_agent_log_input_keeps_json_null(migrated: str) -> None:
    """input은 계약상 JSON 값 전체를 받고 NOT NULL이라, null 입력은 JSON null로 남는다."""
    data = {**load("valid", "agent_log")[0]["data"], "input": None}

    with psycopg.connect(migrated) as conn:
        insert(conn, "agent_logs", data)

        row = conn.execute(
            "SELECT jsonb_typeof(input) FROM agent_logs WHERE id = %s", (data["id"],)
        ).fetchone()
        assert row == ("null",)
