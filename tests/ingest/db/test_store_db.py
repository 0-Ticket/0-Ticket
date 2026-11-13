"""soc.ingest.store의 원본·체크포인트·이력 저장을 실제 PostgreSQL로 확인한다(#218, db 마커)."""

import copy
import json
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from soc.contracts import ContractError, to_epoch_ms
from soc.db.migrate import migrate
from soc.ingest.store import load_checkpoint, record_run, save_page

pytestmark = pytest.mark.db

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ingest"
TARGET = ("elk-dev", "alert", ".alerts-security.alerts-default")


@pytest.fixture
def conn(temp_database: str) -> Iterator[psycopg.Connection]:
    migrate(temp_database)
    with psycopg.connect(temp_database, autocommit=True) as connection:
        yield connection


@pytest.fixture
def page() -> dict:
    return json.loads((FIXTURES / "store_page.json").read_text(encoding="utf-8"))


def raw_rows(conn: psycopg.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT id, kind, siem_profile, siem_ref, fetched_at, original_text FROM raw_records"
        " ORDER BY siem_ref"
    ).fetchall()
    return [
        {
            "id": id_,
            "kind": kind,
            "siem_profile": profile,
            "siem_ref": ref,
            "fetched_at": to_epoch_ms(fetched_at),
            "original_text": original_text,
        }
        for id_, kind, profile, ref, fetched_at, original_text in rows
    ]


def next_checkpoint(page: dict, time_ms: int) -> dict:
    return {**page["checkpoint"], "cursor": {"time_ms": time_ms}, "updated_at": time_ms + 1000}


def test_page_and_checkpoint_are_saved(conn: psycopg.Connection, page: dict) -> None:
    assert load_checkpoint(conn, *TARGET) is None

    assert save_page(conn, page["records"], page["checkpoint"]) == (2, 0)

    assert raw_rows(conn) == page["records"]
    assert load_checkpoint(conn, *TARGET) == page["checkpoint"]


def test_same_id_in_two_indexes_is_stored_twice(conn: psycopg.Connection, page: dict) -> None:
    """ELK _id는 인덱스 안에서만 유일하다. siem_ref(<_index>/<_id>)가 달라 둘 다 남는다."""
    assert {json.loads(r["original_text"])["_id"] for r in page["records"]} == {"a1b2c3"}

    save_page(conn, page["records"], page["checkpoint"])

    assert [r["siem_ref"] for r in raw_rows(conn)] == [
        ".internal.alerts-security.alerts-default-000001/a1b2c3",
        ".internal.alerts-security.alerts-default-000002/a1b2c3",
    ]


def test_saving_same_documents_again_keeps_originals(conn: psycopg.Connection, page: dict) -> None:
    save_page(conn, page["records"], page["checkpoint"])
    before = raw_rows(conn)

    # 다음 실행이 gte로 다시 조회해 같은 문서를 새 id와 바뀐 내용으로 다시 만든 경우
    again = copy.deepcopy(page["records"])
    for number, record in enumerate(again, start=301):
        record["id"] = f"raw_01a19f93-1150-7000-8000-000000000{number}"
        hit = json.loads(record["original_text"])
        hit["_source"]["changed"] = True
        record["original_text"] = json.dumps(hit, ensure_ascii=True)
    later = next_checkpoint(page, 1793678600000)

    assert save_page(conn, again, later) == (0, 0)
    assert raw_rows(conn) == before
    assert load_checkpoint(conn, *TARGET) == later


def test_contract_rejection_writes_nothing(conn: psycopg.Connection, page: dict) -> None:
    first, second = page["records"]
    save_page(conn, [first], page["checkpoint"])

    broken = {**second, "kind": "log"}
    with pytest.raises(ContractError):
        save_page(conn, [second, broken], next_checkpoint(page, 1793678600000))

    assert raw_rows(conn) == [first]
    assert load_checkpoint(conn, *TARGET) == page["checkpoint"]


def test_rejected_checkpoint_writes_no_records(conn: psycopg.Connection, page: dict) -> None:
    broken = {**page["checkpoint"], "cursor": [1793678579000]}
    with pytest.raises(ContractError):
        save_page(conn, page["records"], broken)

    assert raw_rows(conn) == []
    assert load_checkpoint(conn, *TARGET) is None


def test_db_failure_on_checkpoint_rolls_back_records(conn: psycopg.Connection, page: dict) -> None:
    # 원본을 넣은 뒤 체크포인트를 쓸 때 DB 오류가 나게 한다
    conn.execute(
        "CREATE FUNCTION fail_checkpoint() RETURNS trigger LANGUAGE plpgsql"
        " AS $$ BEGIN RAISE EXCEPTION 'injected failure'; END $$"
    )
    conn.execute(
        "CREATE TRIGGER fail_checkpoint BEFORE INSERT OR UPDATE ON ingest_checkpoints"
        " FOR EACH ROW EXECUTE FUNCTION fail_checkpoint()"
    )

    with pytest.raises(psycopg.errors.RaiseException):
        save_page(conn, page["records"], page["checkpoint"])

    assert raw_rows(conn) == []
    assert load_checkpoint(conn, *TARGET) is None


def run_rows(conn: psycopg.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT siem_profile, source_kind, source_key, started_at, finished_at, outcome, pages,"
        " inserted, quarantined FROM ingest_runs ORDER BY id"
    ).fetchall()
    return [
        {
            "siem_profile": profile,
            "source_kind": kind,
            "source_key": key,
            "started_at": to_epoch_ms(started_at),
            "finished_at": to_epoch_ms(finished_at),
            "outcome": outcome,
            "pages": pages,
            "inserted": inserted,
            "quarantined": quarantined,
        }
        for (
            profile,
            kind,
            key,
            started_at,
            finished_at,
            outcome,
            pages,
            inserted,
            quarantined,
        ) in rows
    ]


def run_of(outcome: str, pages: int, inserted: int, started_at: int) -> dict:
    profile, kind, key = TARGET
    return {
        "siem_profile": profile,
        "source_kind": kind,
        "source_key": key,
        "started_at": started_at,
        "finished_at": started_at + 500,
        "outcome": outcome,
        "pages": pages,
        "inserted": inserted,
        "quarantined": 0,
    }


def test_runs_accumulate_and_leave_checkpoint_alone(conn: psycopg.Connection, page: dict) -> None:
    save_page(conn, page["records"], page["checkpoint"])
    runs = [run_of("ok", 1, 2, 1793678570000), run_of("http_status", 0, 0, 1793678700000)]

    for run in runs:
        record_run(conn, run)

    assert run_rows(conn) == runs
    assert load_checkpoint(conn, *TARGET) == page["checkpoint"]


def test_rejected_run_writes_nothing(conn: psycopg.Connection) -> None:
    with pytest.raises(ContractError):
        record_run(conn, run_of("HTTP 401 Unauthorized", 0, 0, 1793678700000))

    assert run_rows(conn) == []


@pytest.mark.parametrize(
    "values",
    [
        {"source_kind": "log"},
        {"siem_profile": ""},
        {"source_key": ""},
        {"cursor": "[]"},
    ],
)
def test_checks_reject_broken_rows(conn: psycopg.Connection, values: dict) -> None:
    row = {
        "siem_profile": "elk-dev",
        "source_kind": "alert",
        "source_key": ".alerts-security.alerts-default",
        "cursor": "{}",
        "updated_at": "2026-11-04T00:00:00Z",
    } | values
    columns = ", ".join(row)
    placeholders = ", ".join(["%s"] * len(row))
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            f"INSERT INTO ingest_checkpoints ({columns}) VALUES ({placeholders})",
            list(row.values()),
        )


@pytest.mark.parametrize(
    "values",
    [
        {"source_kind": "log"},
        {"siem_profile": ""},
        {"source_key": ""},
        {"outcome": "HTTP 401 Unauthorized"},
        {"outcome": "timeout\n"},
        {"pages": -1},
        {"inserted": -1},
        {"quarantined": -1},
        {"finished_at": "2026-11-03T23:59:59Z"},
    ],
)
def test_run_checks_reject_broken_rows(conn: psycopg.Connection, values: dict) -> None:
    row = {
        "siem_profile": "elk-dev",
        "source_kind": "alert",
        "source_key": ".alerts-security.alerts-default",
        "started_at": "2026-11-04T00:00:00Z",
        "finished_at": "2026-11-04T00:00:01Z",
        "outcome": "ok",
        "pages": 0,
        "inserted": 0,
    } | values
    columns = ", ".join(row)
    placeholders = ", ".join(["%s"] * len(row))
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            f"INSERT INTO ingest_runs ({columns}) VALUES ({placeholders})", list(row.values())
        )


@pytest.mark.parametrize("name", ["nul_doc.json", "lone_surrogate_doc.json", "backslash_doc.json"])
def test_special_characters_are_saved_and_restore_the_hit(
    conn: psycopg.Connection, page: dict, name: str
) -> None:
    """NUL·짝 없는 서로게이트·백슬래시 문서도 저장이 실패하지 않고 원래 hit로 돌아온다(#277)."""
    hit = json.loads((FIXTURES / name).read_text(encoding="utf-8"))
    record = {
        "id": "raw_01a19f93-1150-7000-8000-000000000401",
        "kind": "event",
        "siem_profile": "elk-dev",
        "siem_ref": f"{hit['_index']}/{hit['_id']}",
        "fetched_at": 1793678580000,
        "original_text": json.dumps(hit, ensure_ascii=True),
    }

    assert save_page(conn, [record], next_checkpoint(page, 1793678600000)) == (1, 0)

    (stored,) = raw_rows(conn)
    assert json.loads(stored["original_text"]) == hit
