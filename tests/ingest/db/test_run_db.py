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


def test_rejected_page_rolls_back_and_next_run_resumes(conn: psycopg.Connection) -> None:
    failed = run_with(
        conn, FakeElk({"logs-web-*": ["elk_events_page1.json", "elk_bad_record.json"]})
    )
    assert (failed.pages, failed.inserted, failed.failure) == (1, 2, "contract_rejected")
    assert stored(conn) == [APACHE + "/dup-1", NGINX + "/dup-1"]  # 두 인덱스의 같은 _id
    assert checkpoints(conn) == [{"time_ms": 1793754000000}]
    assert runs(conn) == [("contract_rejected", 1, 2)]

    fake = FakeElk({"logs-web-*": ["elk_events_page1.json", "elk_events_page2.json"]})
    resumed = run_with(conn, fake)
    assert fake.search_bodies()[0]["query"]["range"]["@timestamp"]["gte"] == 1793754000000
    assert (resumed.pages, resumed.inserted, resumed.failure) == (2, 1, None)
    assert stored(conn) == [APACHE + "/dup-1", NGINX + "/dup-1", NGINX + "/evt-3"]
    assert checkpoints(conn) == [{"time_ms": 1793754300000}]
    assert runs(conn) == [("contract_rejected", 1, 2), ("ok", 2, 1)]


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
