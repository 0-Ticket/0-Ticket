"""수집 실행을 실제 PostgreSQL 저장소로 확인한다(#218, db 마커). ELK는 FakeElk다."""

from collections.abc import Iterator

import psycopg
import pytest
from fake_elk import FakeElk, make_settings

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


def checkpoint(conn: psycopg.Connection) -> tuple:
    return conn.execute("SELECT cursor, last_error FROM ingest_checkpoints").fetchone()


def test_rejected_page_rolls_back_and_next_run_resumes(conn: psycopg.Connection) -> None:
    failed = run_with(
        conn, FakeElk({"logs-web-*": ["elk_events_page1.json", "elk_bad_record.json"]})
    )
    assert (failed.pages, failed.inserted, failed.failure) == (1, 2, "contract_rejected")
    assert stored(conn) == [APACHE + "/dup-1", NGINX + "/dup-1"]  # 두 인덱스의 같은 _id
    assert checkpoint(conn) == ({"time_ms": 1793754000000}, "contract_rejected")

    fake = FakeElk({"logs-web-*": ["elk_events_page1.json", "elk_events_page2.json"]})
    resumed = run_with(conn, fake)
    assert fake.search_bodies()[0]["query"]["range"]["@timestamp"]["gte"] == 1793754000000
    assert (resumed.pages, resumed.inserted, resumed.failure) == (2, 1, None)
    assert stored(conn) == [APACHE + "/dup-1", NGINX + "/dup-1", NGINX + "/evt-3"]
    assert checkpoint(conn) == ({"time_ms": 1793754300000}, None)
