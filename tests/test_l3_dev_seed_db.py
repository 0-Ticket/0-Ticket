"""개발용 시드 넣기·다시 넣기·지우기를 실제 PostgreSQL로 확인한다(#224, db 마커)."""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

from soc.agent import AgentResult
from soc.agent.agent_log import PostgresLogSink
from soc.contracts import to_datetime, to_epoch_ms
from soc.db.migrate import migrate
from soc.ids import new_id
from soc.l3.config import load_config
from soc.l3.hunt.dev_seed import SEED_PROFILE, SeedInUse, remove_seed, run_dev_seed, seed
from soc.l3.hunt.settings import read_hunt_settings
from soc.l3.hunt.verify import HuntVerifier

pytestmark = pytest.mark.db

FIXTURES = Path(__file__).parent / "fixtures"
OTHER = json.loads((FIXTURES / "l3_hunt" / "seed.json").read_text(encoding="utf-8"))
AGENT_LOG = json.loads((FIXTURES / "contracts" / "valid" / "agent_log.json").read_text("utf-8"))
NOW = datetime(2026, 11, 5, 3, 0, tzinfo=UTC)
TABLES = ("raw_records", "alerts", "events", "hunts", "tickets")


def insert_row(conn: psycopg.Connection, table: str, row: dict[str, Any]) -> None:
    times = {"fetched_at", "time", "created_at", "updated_at", "verified_at"}
    jsonb = {"entities", "assets", "triage", "ocsf", "details", "verdict"}
    values = []
    for key, value in row.items():
        if value is not None and key in times:
            value = to_datetime(value)
        elif value is not None and key in jsonb:
            value = Jsonb(value)
        values.append(value)
    conn.execute(
        sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
            sql.Identifier(table),
            sql.SQL(", ").join(map(sql.Identifier, row)),
            sql.SQL(", ").join(sql.Placeholder() * len(row)),
        ),
        values,
    )


@pytest.fixture
def db(temp_database: str) -> str:
    migrate(temp_database)
    return temp_database


@pytest.fixture
def conn(db: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(db, autocommit=True) as connection:
        yield connection


def counts(conn: psycopg.Connection) -> dict[str, int]:
    return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES}  # type: ignore[index]


def seeded_hunts(conn: psycopg.Connection) -> dict[str, str]:
    rows = conn.execute(
        "SELECT details->>'scenario', id FROM hunts WHERE details @> '{\"dev_seed\": true}'"
    ).fetchall()
    return dict(rows)


def insert_other_rows(conn: psycopg.Connection) -> None:
    """시드가 아닌 행(#223 샘플의 원본·Alert·Event)과 시드가 아닌 Hunt 하나."""
    for table in ("raw_records", "alerts", "events"):
        for row in OTHER[table]:
            insert_row(conn, table, row)
    insert_row(
        conn,
        "hunts",
        {
            "id": new_id("hnt"),
            "hunt_run_id": new_id("hrn"),
            "status": "pending",
            "hypothesis": "시드가 아닌 가설",
            "attack_techniques": ["T1190"],
            "confidence": None,
            "reason": None,
            "evidence_ids": [],
            "entities": [],
            "attempts": 0,
            "verified_at": None,
            "created_at": to_epoch_ms(NOW),
            "updated_at": to_epoch_ms(NOW),
            "details": {},
        },
    )


def confirm_threat(db: str, conn: psycopg.Connection) -> str:
    """가짜 실행 결과로 위협 있음 Hunt를 confirmed로 만들어 L3 Ticket을 남긴다. Ticket ID."""
    hunt_id = seeded_hunts(conn)["threat"]
    alert_id = conn.execute(
        "SELECT a.id FROM alerts a JOIN raw_records r ON r.id = a.raw_id WHERE r.siem_profile = %s",
        (SEED_PROFILE,),
    ).fetchone()[0]  # type: ignore[index]
    output = {
        "result": "confirmed",
        "confidence": 0.9,
        "reason": "웹셸 업로드와 실행 기록이 있다",
        "evidence_ids": [alert_id],
        "entities": [],
    }
    result = AgentResult(
        ok=True,
        output=output,
        failure=None,
        detail=None,
        run_id=new_id("run"),
        cited_evidence_ids=[alert_id],
    )
    settings = read_hunt_settings(load_config()["l3"])
    HuntVerifier(db, settings, run=lambda task: result, clock=lambda: NOW).handle(hunt_id)
    return conn.execute("SELECT id FROM tickets WHERE hunt_id = %s", (hunt_id,)).fetchone()[0]  # type: ignore[index]


def test_seed_inserts_two_pending_hunts_with_records(conn: psycopg.Connection) -> None:
    made = seed(conn, now=NOW)

    hunts = seeded_hunts(conn)
    assert set(hunts) == {"threat", "no_threat"}
    assert made.hunt_ids == hunts
    statuses = conn.execute("SELECT status, attempts FROM hunts").fetchall()
    assert statuses == [("pending", 0), ("pending", 0)]
    assert counts(conn) == {
        "raw_records": 6,
        "alerts": 1,
        "events": 5,
        "hunts": 2,
        "tickets": 0,
    }
    assert made.inserted == {"hunts": 2, "alerts": 1, "events": 5, "raw_records": 6}
    profiles = conn.execute("SELECT DISTINCT siem_profile FROM raw_records").fetchall()
    assert profiles == [(SEED_PROFILE,)]
    # 레코드 시각은 넣은 시점 기준 7일(lookback_days) 안이다
    (oldest, newest) = conn.execute("SELECT min(time), max(time) FROM events").fetchone()  # type: ignore[misc]
    assert (NOW - oldest).days < 7 and newest < NOW


def test_seed_again_replaces_previous_seed(conn: psycopg.Connection) -> None:
    first = seed(conn, now=NOW)
    before = counts(conn)

    second = seed(conn, now=NOW)

    assert counts(conn) == before
    assert set(first.hunt_ids.values()).isdisjoint(second.hunt_ids.values())
    assert second.removed == {"tickets": 0, "hunts": 2, "alerts": 1, "events": 5, "raw_records": 6}


def test_remove_deletes_only_seed_rows_and_keeps_agent_logs(
    db: str, conn: psycopg.Connection
) -> None:
    insert_other_rows(conn)
    other = counts(conn)
    made = seed(conn, now=NOW)
    log = {**AGENT_LOG[-1]["data"], "subject_id": made.hunt_ids["threat"]}
    PostgresLogSink(db).write([log])
    ticket_id = confirm_threat(db, conn)

    removed = remove_seed(conn)

    assert removed == {"tickets": 1, "hunts": 2, "alerts": 1, "events": 5, "raw_records": 6}
    assert counts(conn) == other
    assert seeded_hunts(conn) == {}
    assert conn.execute("SELECT count(*) FROM tickets WHERE id = %s", (ticket_id,)).fetchone() == (
        0,
    )
    # Agent Log는 실측 원본이라 남긴다
    assert conn.execute("SELECT count(*) FROM agent_logs").fetchone() == (1,)


def test_remove_refuses_when_seed_ticket_is_in_an_incident(
    db: str, conn: psycopg.Connection
) -> None:
    seed(conn, now=NOW)
    ticket_id = confirm_threat(db, conn)
    incident = {**OTHER["incidents"][0], "ticket_ids": [ticket_id], "status": "analyzing"}
    insert_row(conn, "incidents", incident)
    before = counts(conn)

    with pytest.raises(SeedInUse):
        remove_seed(conn)
    with pytest.raises(SeedInUse):
        seed(conn, now=NOW)

    assert counts(conn) == before


def test_remove_with_nothing_seeded_is_fine(conn: psycopg.Connection) -> None:
    assert remove_seed(conn) == {
        "tickets": 0,
        "hunts": 0,
        "alerts": 0,
        "events": 0,
        "raw_records": 0,
    }


def test_command_seeds_and_prints_counts_and_hunt_ids_only(db: str) -> None:
    out: list[str] = []
    err: list[str] = []

    code = run_dev_seed(db, clock=lambda: NOW, out=out.append, err=err.append)

    assert code == 0 and err == []
    text = "\n".join(out)
    assert "개발 DB 전용" in text
    with psycopg.connect(db) as conn:
        hunts = seeded_hunts(conn)
    assert hunts["threat"] in text and hunts["no_threat"] in text
    for scenario in json.loads((FIXTURES / "l3_hunt" / "dev_seed.json").read_text("utf-8"))[
        "scenarios"
    ]:
        assert scenario["hunt"]["hypothesis"] not in text  # 가설 본문은 출력하지 않는다


def test_command_remove_only_removes(db: str) -> None:
    with psycopg.connect(db, autocommit=True) as conn:
        seed(conn, now=NOW)
    out: list[str] = []

    code = run_dev_seed(db, remove=True, clock=lambda: NOW, out=out.append, err=out.append)

    assert code == 0
    with psycopg.connect(db) as conn:
        assert counts(conn) == {t: 0 for t in TABLES}
    assert any("hunts 2" in line for line in out)


def test_command_refused_exits_1(db: str) -> None:
    with psycopg.connect(db, autocommit=True) as conn:
        seed(conn, now=NOW)
        ticket_id = confirm_threat(db, conn)
        incident = {**OTHER["incidents"][0], "ticket_ids": [ticket_id], "status": "analyzing"}
        insert_row(conn, "incidents", incident)
    err: list[str] = []

    assert run_dev_seed(db, clock=lambda: NOW, out=err.append, err=err.append) == 1
    assert any("Incident" in line for line in err)


def test_command_without_database_url_exits_2() -> None:
    err: list[str] = []
    assert run_dev_seed(None, out=err.append, err=err.append) == 2
    assert any("DATABASE_URL" in line for line in err)


def test_command_db_error_exits_1_without_address(db: str) -> None:
    bad = "postgresql://nobody:secret-pw@127.0.0.1:1/none?connect_timeout=2"
    err: list[str] = []

    assert run_dev_seed(bad, out=err.append, err=err.append) == 1
    text = "\n".join(err)
    assert "secret-pw" not in text and "127.0.0.1" not in text
