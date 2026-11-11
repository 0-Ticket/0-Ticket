"""수집 실행과 실행 이력을 실제 PostgreSQL 저장소로 확인한다(#218, db 마커). ELK는 FakeElk다."""

from collections.abc import Iterator

import psycopg
import pytest
from fake_elk import FakeElk, make_settings, respond

from soc.contracts import to_epoch_ms
from soc.db.migrate import migrate
from soc.ingest.run import run

pytestmark = pytest.mark.db

NGINX = ".ds-logs-nginx.access-default-2026.11.04-000001"
APACHE = ".ds-logs-apache.access-default-2026.11.04-000001"


@pytest.fixture
def conn(temp_database: str) -> Iterator[psycopg.Connection]:
    migrate(temp_database)
    with psycopg.connect(temp_database, autocommit=True) as connection:
        yield connection


def run_with(conn: psycopg.Connection, fake: FakeElk):
    with fake.client() as client:
        (result,) = run(make_settings(), conn, client)
    return result


def stored(conn: psycopg.Connection) -> list[str]:
    rows = conn.execute("SELECT siem_ref FROM raw_records ORDER BY siem_ref").fetchall()
    return [row[0] for row in rows]


def checkpoints(conn: psycopg.Connection) -> list[dict]:
    return [row[0] for row in conn.execute("SELECT cursor FROM ingest_checkpoints").fetchall()]


def runs(conn: psycopg.Connection) -> list[tuple]:
    return conn.execute("SELECT outcome, pages, inserted FROM ingest_runs ORDER BY id").fetchall()


def test_nul_page_is_stored_and_next_run_resumes(conn: psycopg.Connection) -> None:
    """NUL이 든 문서가 있어도 페이지는 실패 없이 저장되고(#277), 다음 실행이 이어서 조회한다."""
    first = run_with(
        conn, FakeElk({"logs-web-*": ["elk_events_page1.json", "elk_nul_record.json"]})
    )
    assert (first.pages, first.inserted, first.failure) == (2, 3, None)
    assert stored(conn) == [APACHE + "/dup-1", NGINX + "/dup-1", NGINX + "/nul-1"]
    assert runs(conn) == [("ok", 2, 3)]

    fake = FakeElk({"logs-web-*": ["elk_events_page1.json", "elk_events_page2.json"]})
    resumed = run_with(conn, fake)
    assert fake.search_bodies()[0]["query"]["range"]["@timestamp"]["gte"] == 1793754360000
    assert (resumed.pages, resumed.inserted, resumed.failure) == (2, 1, None)
    assert stored(conn) == [APACHE + "/dup-1", NGINX + "/dup-1", NGINX + "/evt-3", NGINX + "/nul-1"]
    assert runs(conn) == [("ok", 2, 3), ("ok", 2, 1)]


def test_db_error_on_page_rolls_back_and_next_run_resumes(conn: psycopg.Connection) -> None:
    """페이지 중간의 원본 쓰기가 DB 오류로 실패하면 그 페이지만 롤백되고 다음 실행이 이어간다(#277).

    계약 위반은 hit 데이터만으로 만들 수 없어(elk._read_page가 먼저 막는다), 특정 원본의 INSERT를
    트리거로 실패시켜 롤백 경로를 본다. 실패 종류는 contract_rejected가 아니라 db_error다.
    """
    conn.execute(
        "CREATE FUNCTION reject_page_row() RETURNS trigger LANGUAGE plpgsql"
        " AS $$ BEGIN IF NEW.siem_ref LIKE '%/reject-1' THEN"
        " RAISE EXCEPTION 'injected row failure'; END IF; RETURN NEW; END $$"
    )
    conn.execute(
        "CREATE TRIGGER reject_page_row BEFORE INSERT ON raw_records"
        " FOR EACH ROW EXECUTE FUNCTION reject_page_row()"
    )

    first = run_with(
        conn,
        FakeElk({"logs-web-*": ["elk_events_page1.json", "elk_events_page2_reject.json"]}),
    )

    # page2의 evt-3는 같은 트랜잭션이라 함께 롤백된다
    assert (first.pages, first.inserted, first.failure) == (1, 2, "db_error")
    assert stored(conn) == [APACHE + "/dup-1", NGINX + "/dup-1"]
    assert checkpoints(conn) == [{"time_ms": 1793754000000}]
    assert runs(conn) == [("db_error", 1, 2)]

    conn.execute("DROP TRIGGER reject_page_row ON raw_records")
    fake = FakeElk(
        {"logs-web-*": ["elk_events_page1.json", "elk_events_page2_reject.json", "elk_empty.json"]}
    )
    resumed = run_with(conn, fake)

    assert fake.search_bodies()[0]["query"]["range"]["@timestamp"]["gte"] == 1793754000000
    assert (resumed.pages, resumed.inserted, resumed.failure) == (2, 2, None)
    assert stored(conn) == [
        APACHE + "/dup-1",
        NGINX + "/dup-1",
        NGINX + "/evt-3",
        NGINX + "/reject-1",
    ]
    assert checkpoints(conn) == [{"time_ms": 1793754300000}]
    assert runs(conn) == [("db_error", 1, 2), ("ok", 2, 2)]


def test_first_page_failure_and_empty_run_leave_history_only(conn: psycopg.Connection) -> None:
    failed = run_with(conn, FakeElk({"logs-web-*": [respond(500, {"error": "SECRET-BODY"})]}))
    empty = run_with(conn, FakeElk({"logs-web-*": ["elk_empty.json"]}))

    assert (failed.failure, empty.failure) == ("http_status", None)
    assert checkpoints(conn) == []  # 성공한 페이지가 없으니 다음 실행도 처음부터 조회한다
    assert runs(conn) == [("http_status", 0, 0), ("ok", 0, 0)]
    started_at, finished_at = conn.execute(
        "SELECT started_at, finished_at FROM ingest_runs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    assert to_epoch_ms(started_at) == empty.started_at
    assert finished_at >= started_at


def test_failed_run_record_keeps_saved_pages(conn: psycopg.Connection) -> None:
    # 원본·체크포인트를 커밋한 뒤 이력 쓰기만 DB 오류가 나게 한다
    conn.execute(
        "CREATE FUNCTION fail_run() RETURNS trigger LANGUAGE plpgsql"
        " AS $$ BEGIN RAISE EXCEPTION 'injected failure'; END $$"
    )
    conn.execute(
        "CREATE TRIGGER fail_run BEFORE INSERT ON ingest_runs"
        " FOR EACH ROW EXECUTE FUNCTION fail_run()"
    )

    result = run_with(conn, FakeElk({"logs-web-*": ["elk_events_page2.json"]}))

    assert (result.pages, result.inserted, result.failure) == (1, 1, None)
    assert stored(conn) == [NGINX + "/evt-3"]
    assert checkpoints(conn) == [{"time_ms": 1793754300000}]
    assert runs(conn) == []
