"""수집 페이지와 체크포인트 저장(soc.ingest.store)을 실제 PostgreSQL로 확인한다(#218, db 마커)."""

import copy
import json
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from soc.contracts import ContractError, to_epoch_ms
from soc.db.migrate import migrate
from soc.ingest.store import load_checkpoint, record_failure, save_page

pytestmark = pytest.mark.db

FIXTURES = Path(__file__).parent / "fixtures" / "ingest"
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
        "SELECT id, kind, siem_profile, siem_ref, fetched_at, original FROM raw_records"
        " ORDER BY siem_ref"
    ).fetchall()
    return [
        {
            "id": id_,
            "kind": kind,
            "siem_profile": profile,
            "siem_ref": ref,
            "fetched_at": to_epoch_ms(fetched_at),
            "original": original,
        }
        for id_, kind, profile, ref, fetched_at, original in rows
    ]


def next_checkpoint(page: dict, time_ms: int) -> dict:
    return {**page["checkpoint"], "cursor": {"time_ms": time_ms}, "updated_at": time_ms + 1000}


def test_page_and_checkpoint_are_saved(conn: psycopg.Connection, page: dict) -> None:
    assert load_checkpoint(conn, *TARGET) is None

    assert save_page(conn, page["records"], page["checkpoint"]) == 2

    assert raw_rows(conn) == page["records"]
    assert load_checkpoint(conn, *TARGET) == page["checkpoint"]


def test_same_id_in_two_indexes_is_stored_twice(conn: psycopg.Connection, page: dict) -> None:
    """ELK _id는 인덱스 안에서만 유일하다. siem_ref(<_index>/<_id>)가 달라 둘 다 남는다."""
    assert {r["original"]["_id"] for r in page["records"]} == {"a1b2c3"}

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
        record["original"]["_source"]["changed"] = True
    later = next_checkpoint(page, 1793678600000)

    assert save_page(conn, again, later) == 0
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
    broken = {**page["checkpoint"], "last_error": "HTTP 401 Unauthorized"}
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


def test_record_failure_keeps_cursor(conn: psycopg.Connection, page: dict) -> None:
    save_page(conn, page["records"], page["checkpoint"])

    record_failure(conn, *TARGET, "http_status", 1793678700000)

    assert load_checkpoint(conn, *TARGET) == {
        **page["checkpoint"],
        "updated_at": 1793678700000,
        "last_error": "http_status",
    }

    # 다음 페이지가 성공하면 체크포인트의 last_error가 비워진다
    later = next_checkpoint(page, 1793678800000)
    save_page(conn, [], later)
    assert load_checkpoint(conn, *TARGET) == later


def test_record_failure_without_checkpoint_creates_empty_cursor_row(
    conn: psycopg.Connection,
) -> None:
    """첫 페이지부터 실패해도 원인이 남고, 빈 cursor라 다음 실행은 처음부터 조회한다."""
    record_failure(conn, *TARGET, "timeout", 1793678700000)

    saved = load_checkpoint(conn, *TARGET)
    assert saved is not None
    assert saved["cursor"] == {}
    assert saved["last_error"] == "timeout"


@pytest.mark.parametrize(
    "values",
    [
        {"source_kind": "log"},
        {"siem_profile": ""},
        {"source_key": ""},
        {"cursor": "[]"},
        {"last_error": "HTTP 401 Unauthorized"},
        {"last_error": "timeout\n"},
    ],
)
def test_checks_reject_broken_rows(conn: psycopg.Connection, values: dict) -> None:
    row = {
        "siem_profile": "elk-dev",
        "source_kind": "alert",
        "source_key": ".alerts-security.alerts-default",
        "cursor": "{}",
        "updated_at": "2026-11-04T00:00:00Z",
        "last_error": None,
    } | values
    columns = ", ".join(row)
    placeholders = ", ".join(["%s"] * len(row))
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            f"INSERT INTO ingest_checkpoints ({columns}) VALUES ({placeholders})",
            list(row.values()),
        )
