"""0106 마이그레이션의 전제(빈 raw_records)를 실제 PostgreSQL로 확인한다(db 마커).

raw_records가 비어 있지 않으면 적용을 멈추고, 비어 있으면 원본 열을 바꾼다.
"""

import shutil
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import psycopg
import pytest

from soc.db.migrate import MIGRATIONS_DIR, MigrationError, migrate

pytestmark = pytest.mark.db

PREVIOUS = "0105_l1_attempts.sql"


@pytest.fixture
def before_0106(tmp_path: Path) -> Path:
    """0106 전 마이그레이션만 든 폴더."""
    for path in MIGRATIONS_DIR.glob("*.sql"):
        if path.name <= PREVIOUS:
            shutil.copy(path, tmp_path / path.name)
    return tmp_path


@pytest.fixture
def db_before(temp_database: str, before_0106: Path) -> Iterator[psycopg.Connection]:
    migrate(temp_database, before_0106)
    with psycopg.connect(temp_database, autocommit=True) as connection:
        yield connection


def insert_raw(conn: psycopg.Connection) -> None:
    conn.execute(
        "INSERT INTO raw_records (id, kind, siem_profile, siem_ref, fetched_at, original)"
        " VALUES ('raw_01a19f93-1150-7000-8000-000000000501', 'event', 'elk-dev', 'idx/1',"
        " now(), '{}')"
    )


def test_migration_stops_when_raw_records_is_not_empty(
    db_before: psycopg.Connection, temp_database: str
) -> None:
    insert_raw(db_before)

    with pytest.raises(MigrationError, match="raw_records"):
        migrate(temp_database)

    columns = {
        row[0]
        for row in db_before.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_name = 'raw_records'"
        )
    }
    assert "original" in columns
    assert "original_text" not in columns


def test_migration_checks_after_an_inflight_insert_finishes(
    temp_database: str, before_0106: Path
) -> None:
    """빈 표 검사와 열 변경 사이에 수집이 끼어들어도 비어 있지 않으면 멈춘다."""
    migrate(temp_database, before_0106)

    with ThreadPoolExecutor(max_workers=1) as executor:
        with psycopg.connect(temp_database) as writer:
            insert_raw(writer)
            migration = executor.submit(migrate, temp_database)

            deadline = time.monotonic() + 5
            waiting = False
            while time.monotonic() < deadline:
                with psycopg.connect(temp_database, autocommit=True) as inspector:
                    (waiting,) = inspector.execute(
                        "SELECT EXISTS (SELECT 1 FROM pg_locks"
                        " WHERE relation = 'public.raw_records'::regclass"
                        " AND mode = 'AccessExclusiveLock' AND NOT granted)"
                    ).fetchone()
                if waiting:
                    break
                time.sleep(0.01)
            assert waiting, "마이그레이션이 진행 중인 insert를 기다리지 않았다"
            writer.commit()

        with pytest.raises(MigrationError, match="raw_records"):
            migration.result(timeout=5)


def test_empty_raw_records_gets_original_text(
    db_before: psycopg.Connection, temp_database: str
) -> None:
    migrate(temp_database)

    columns = {
        row[0]: row[1]
        for row in db_before.execute(
            "SELECT column_name, data_type FROM information_schema.columns"
            " WHERE table_name = 'raw_records'"
        )
    }
    assert columns["original_text"] == "text"
    assert "original" not in columns
    with pytest.raises(psycopg.errors.CheckViolation):
        db_before.execute(
            "INSERT INTO raw_records (id, kind, siem_profile, siem_ref, fetched_at, original_text)"
            " VALUES ('raw_01a19f93-1150-7000-8000-000000000502', 'event', 'elk-dev', 'idx/2',"
            " now(), '[1]')"
        )
