"""수동 수집의 잠금, 체크포인트 후퇴 방지, 정규화가 보는 범위를 실제 PostgreSQL로 확인한다(#317)."""

from collections.abc import Iterator

import psycopg
import pytest
from fake_elk import FakeElk, make_settings

from soc.db.migrate import migrate
from soc.ids import new_id
from soc.ingest import store
from soc.ingest.run import run
from soc.normalize import store as normalize_store

pytestmark = pytest.mark.db

NOW = 1_793_800_000_000


@pytest.fixture
def conn(temp_database: str) -> Iterator[psycopg.Connection]:
    migrate(temp_database)
    with psycopg.connect(temp_database, autocommit=True) as connection:
        yield connection


def checkpoint(time_ms: int, updated_at: int | None = None) -> dict:
    return {
        "siem_profile": "elk-test",
        "source_kind": "event",
        "source_key": "logs-web-*",
        "cursor": {"time_ms": time_ms},
        "updated_at": time_ms if updated_at is None else updated_at,
    }


def run_with(conn: psycopg.Connection, fake: FakeElk, since_ms: int | None = None):
    with fake.client() as client:
        (result,) = run(make_settings(), conn, client, since_ms=since_ms, now_ms=NOW)
    return result


def test_checkpoint_only_moves_forward(conn: psycopg.Connection) -> None:
    store.save_page(conn, [], checkpoint(2_000, updated_at=2_000))
    store.save_page(conn, [], checkpoint(1_000, updated_at=9_000))  # 과거 값은 무시한다
    saved = store.load_checkpoint(conn, "elk-test", "event", "logs-web-*")
    assert (saved["cursor"], saved["updated_at"]) == ({"time_ms": 2_000}, 2_000)

    store.save_page(conn, [], checkpoint(3_000))
    assert store.load_checkpoint(conn, "elk-test", "event", "logs-web-*")["cursor"] == {
        "time_ms": 3_000
    }


def test_legacy_empty_cursor_is_replaced(conn: psycopg.Connection) -> None:
    conn.execute(
        "INSERT INTO ingest_checkpoints (siem_profile, source_kind, source_key, cursor, updated_at)"
        " VALUES ('elk-test', 'event', 'logs-web-*', '{}', now())"
    )
    store.save_page(conn, [], checkpoint(1_000))
    saved = store.load_checkpoint(conn, "elk-test", "event", "logs-web-*")
    assert saved["cursor"] == {"time_ms": 1_000}


def test_rereading_old_range_adds_nothing_and_keeps_checkpoint(conn: psycopg.Connection) -> None:
    pages = ["elk_events_page1.json", "elk_events_page2.json"]
    first = run_with(conn, FakeElk({"logs-web-*": list(pages)}))
    assert (first.inserted, first.failure) == (3, None)

    again = run_with(
        conn,
        FakeElk({"logs-web-*": ["elk_events_page1.json", "elk_empty.json"]}),
        1_793_750_000_000,
    )

    assert (again.fetched, again.inserted, again.failure) == (2, 0, None)
    assert conn.execute("SELECT count(*) FROM raw_records").fetchone() == (3,)
    saved = store.load_checkpoint(conn, "elk-test", "event", "logs-web-*")
    assert saved["cursor"] == {"time_ms": 1_793_754_300_000}


def test_second_identical_run_stores_zero_new(conn: psycopg.Connection) -> None:
    pages = ["elk_events_page1.json", "elk_events_page2.json"]
    run_with(conn, FakeElk({"logs-web-*": list(pages)}))
    second = run_with(conn, FakeElk({"logs-web-*": list(pages)}))
    assert (second.inserted, second.quarantined, second.failure) == (0, 0, None)
    assert second.fetched == 3
    assert conn.execute("SELECT count(*) FROM raw_records").fetchone() == (3,)


def test_run_lock_is_exclusive_and_released_with_the_connection(temp_database: str) -> None:
    with (
        psycopg.connect(temp_database, autocommit=True) as first,
        psycopg.connect(temp_database, autocommit=True) as second,
    ):
        assert store.acquire_run_lock(first) is True
        assert store.acquire_run_lock(second) is False
    with psycopg.connect(temp_database, autocommit=True) as third:
        assert store.acquire_run_lock(third) is True  # 연결이 끊기면 풀린다


def test_uncommitted_page_is_invisible_to_normalize(
    conn: psycopg.Connection, temp_database: str
) -> None:
    """저장이 끝나지 않은(커밋 전) 원본은 정규화의 claim 대상이 아니다."""
    record = {
        "id": new_id("raw"),
        "kind": "event",
        "siem_profile": "elk-test",
        "siem_ref": "idx/pending-1",
        "fetched_at": NOW,
        "original_text": "{}",
    }
    with psycopg.connect(temp_database, autocommit=True) as reader:
        with conn.transaction():
            store.save_page(conn, [record], checkpoint(1_000))  # 바깥 트랜잭션 안의 savepoint
            assert normalize_store.claim_pending_batch(reader, "owner-1", 10, 60) == []
        claimed = normalize_store.claim_pending_batch(reader, "owner-1", 10, 60)
    assert [row.id for row in claimed] == [record["id"]]
