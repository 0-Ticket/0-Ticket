"""격리 행·RawRecord·체크포인트·실행 건수를 실제 PostgreSQL에서 확인한다."""

import base64
import hashlib
import json
import shutil
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from soc.contracts import to_datetime
from soc.db.migrate import MIGRATIONS_DIR, migrate
from soc.ingest.quarantine import canonical_json_bytes, quarantine_key, serialize_original
from soc.ingest.store import load_checkpoint, save_page

pytestmark = pytest.mark.db
FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ingest"
TARGET = ("elk-test", "event", "logs-web-*")


@pytest.fixture
def conn(temp_database: str) -> Iterator[psycopg.Connection]:
    migrate(temp_database)
    with psycopg.connect(temp_database, autocommit=True) as connection:
        yield connection


def page() -> dict:
    return json.loads((FIXTURES / "store_page.json").read_text(encoding="utf-8"))


def checkpoint() -> dict:
    names = ("siem_profile", "source_kind", "source_key")
    return page()["checkpoint"] | dict(zip(names, TARGET, strict=True))


def quarantine_record() -> dict:
    profile, kind, key = TARGET
    return {
        "siem_profile": profile,
        "source_kind": kind,
        "source_key": key,
        "siem_ref": (
            "synthetic:v1:n:n:vMTIz:"
            "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        ),
        "reason_code": "non_finite",
        "original_text": '{"_source":{"value":NaN}}',
        "seen_at": 1793678580000,
    }


def insert_quarantine(conn: psycopg.Connection, record: dict) -> None:
    conn.execute(
        "INSERT INTO ingest_quarantine"
        " (siem_profile, source_kind, source_key, siem_ref, reason_code, original_text, seen_at)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s)",
        (
            record["siem_profile"],
            record["source_kind"],
            record["source_key"],
            record["siem_ref"],
            record["reason_code"],
            record["original_text"],
            to_datetime(record["seen_at"]),
        ),
    )


def test_page_saves_raw_quarantine_and_checkpoint_atomically(conn: psycopg.Connection) -> None:
    fixture = page()
    next_cursor = checkpoint()
    raw = fixture["records"][:1]
    quarantined = quarantine_record()

    assert save_page(conn, raw, next_cursor, quarantines=[quarantined]) == (1, 1)
    assert conn.execute("SELECT count(*) FROM raw_records").fetchone() == (1,)
    assert conn.execute("SELECT reason_code, original_text FROM ingest_quarantine").fetchone() == (
        "non_finite",
        '{"_source":{"value":NaN}}',
    )
    assert load_checkpoint(conn, *TARGET) == next_cursor


def test_duplicate_quarantine_rows_do_not_increase_insert_count(conn: psycopg.Connection) -> None:
    quarantined = quarantine_record()

    assert save_page(conn, [], checkpoint(), quarantines=[quarantined]) == (0, 1)
    later_checkpoint = {
        **checkpoint(),
        "cursor": {"time_ms": 1793678600000},
        "updated_at": 1793678600000,
    }
    assert save_page(conn, [], later_checkpoint, quarantines=[quarantined]) == (0, 0)
    assert conn.execute("SELECT count(*) FROM ingest_quarantine").fetchone() == (1,)
    assert load_checkpoint(conn, *TARGET) == later_checkpoint


def test_long_field_tokens_are_hash_bounded_and_fit_the_unique_index(
    conn: psycopg.Connection,
) -> None:
    quarantined = quarantine_record()
    profile, kind, key = TARGET

    def high_entropy(label: str) -> str:
        blocks = (hashlib.sha256(f"{label}:{index}".encode()).hexdigest() for index in range(48))
        return "".join(blocks)[:3000]

    hit = {
        "_index": high_entropy("index"),
        "_id": high_entropy("id"),
        "sort": [high_entropy("sort")],
    }
    quarantined["original_text"] = serialize_original(hit)

    raw_token_bytes = [
        serialize_original(hit["_index"]).encode("ascii"),
        serialize_original(hit["_id"]).encode("ascii"),
        canonical_json_bytes(hit["sort"][0]),
    ]
    legacy_tokens = [
        "v" + base64.urlsafe_b64encode(value).decode("ascii").rstrip("=")
        for value in raw_token_bytes
    ]
    payload = {"source_kind": kind, "source_key": key, "hit": hit}
    legacy_hash = hashlib.sha256(canonical_json_bytes(payload)).hexdigest()
    legacy_ref = f"synthetic:v1:{':'.join(legacy_tokens)}:{legacy_hash}"
    quarantined["siem_ref"] = legacy_ref

    with pytest.raises(psycopg.errors.ProgramLimitExceeded):
        insert_quarantine(conn, quarantined)

    quarantined["siem_ref"] = quarantine_key(kind, key, hit)
    tokens = quarantined["siem_ref"].split(":")[2:5]

    assert all(
        len(token) == 65
        and token[0] == "h"
        and all(character in "0123456789abcdef" for character in token[1:])
        for token in tokens
    )
    assert len(quarantined["original_text"]) > 9000
    assert save_page(conn, [], None, quarantines=[quarantined]) == (0, 1)
    assert save_page(conn, [], None, quarantines=[quarantined]) == (0, 0)
    assert conn.execute(
        "SELECT siem_ref, original_text FROM ingest_quarantine WHERE siem_profile = %s", (profile,)
    ).fetchone() == (quarantined["siem_ref"], serialize_original(hit))


def test_quarantine_insert_failure_rolls_back_raw_rows_and_checkpoint(
    conn: psycopg.Connection,
) -> None:
    fixture = page()
    conn.execute(
        "CREATE FUNCTION reject_quarantine() RETURNS trigger LANGUAGE plpgsql"
        " AS $$ BEGIN RAISE EXCEPTION 'injected quarantine failure'; END $$"
    )
    conn.execute(
        "CREATE TRIGGER reject_quarantine BEFORE INSERT ON ingest_quarantine"
        " FOR EACH ROW EXECUTE FUNCTION reject_quarantine()"
    )

    with pytest.raises(psycopg.errors.RaiseException):
        save_page(
            conn,
            fixture["records"][:1],
            fixture["checkpoint"],
            quarantines=[quarantine_record()],
        )

    assert conn.execute("SELECT count(*) FROM raw_records").fetchone() == (0,)
    assert conn.execute("SELECT count(*) FROM ingest_quarantine").fetchone() == (0,)
    assert load_checkpoint(conn, *TARGET) is None


def test_page_without_checkpoint_keeps_existing_cursor(conn: psycopg.Connection) -> None:
    first_checkpoint = checkpoint()
    save_page(conn, [], first_checkpoint)
    q = quarantine_record()
    q["siem_ref"] += "-later"

    assert save_page(conn, [], None, quarantines=[q]) == (0, 1)

    assert load_checkpoint(conn, *TARGET) == first_checkpoint


def test_quarantine_table_checks_kind_and_reason_without_checking_original_text(
    conn: psycopg.Connection,
) -> None:
    quarantined = quarantine_record()
    quarantined["original_text"] = "outside text with control \x01 and NaN"
    assert save_page(conn, [], None, quarantines=[quarantined]) == (0, 1)
    assert conn.execute("SELECT original_text FROM ingest_quarantine").fetchone() == (
        "outside text with control \x01 and NaN",
    )

    bad_kind = quarantine_record()
    bad_kind["siem_ref"] += "-bad-kind"
    bad_kind["source_kind"] = "log"
    with pytest.raises(psycopg.errors.CheckViolation):
        insert_quarantine(conn, bad_kind)

    bad_reason = quarantine_record()
    bad_reason["siem_ref"] += "-bad-reason"
    bad_reason["reason_code"] = "Not A Code"
    with pytest.raises(psycopg.errors.CheckViolation):
        insert_quarantine(conn, bad_reason)


def test_0107_defaults_existing_run_quarantine_count_to_zero(
    temp_database: str, tmp_path: Path
) -> None:
    before_0107 = tmp_path / "migrations"
    before_0107.mkdir()
    for migration in MIGRATIONS_DIR.glob("*.sql"):
        if migration.name != "0107_ingest_quarantine.sql":
            shutil.copyfile(migration, before_0107 / migration.name)
    migrate(temp_database, before_0107)
    with psycopg.connect(temp_database, autocommit=True) as connection:
        connection.execute(
            "INSERT INTO ingest_runs"
            " (siem_profile, source_kind, source_key, started_at, finished_at, outcome, pages,"
            " inserted)"
            " VALUES ('elk-test', 'event', 'logs-web-*', '2026-11-12T00:00:00Z',"
            " '2026-11-12T00:00:00Z', 'ok', 0, 0)"
        )

    assert migrate(temp_database) == ["0107_ingest_quarantine.sql"]
    with psycopg.connect(temp_database) as connection:
        row = connection.execute("SELECT quarantined FROM ingest_runs").fetchone()
        assert row == (0,)
