"""정규화 상태·임대·저장과 자산 조회를 임시 DB에서 확인한다(db 마커, #234).

원본은 tests/fixtures/normalize/raw.json의 손으로 만든 샘플이다.
"""

import hashlib
import json
import uuid
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from typing import Any

import psycopg
import pytest
from conftest import HiddenUrl

from soc.asset_lookup import AssetLookupError, lookup_assets
from soc.contracts import to_datetime
from soc.db.migrate import migrate
from soc.ids import new_id
from soc.normalize import run as run_module
from soc.normalize.config import Settings
from soc.normalize.mapping import RawRow
from soc.normalize.mapping import normalize as map_normalize
from soc.normalize.run import exit_code, run, run_failed
from soc.normalize.store import claim_failed_batch, claim_pending_batch, save_failure, save_success

pytestmark = pytest.mark.db

_FIXTURE = Path(__file__).parent.parent / "fixtures" / "normalize" / "raw.json"
CASES = json.loads(_FIXTURE.read_text(encoding="utf-8"))
FAILURES = [case["expect"]["error"] for case in CASES if "error" in case["expect"]]
SETTINGS = Settings(
    batch_size=200,
    lease_seconds=600,
    connect_timeout_seconds=5,
    asset_statement_timeout_ms=5000,
)


@pytest.fixture
def migrated(temp_database: HiddenUrl) -> HiddenUrl:
    migrate(temp_database)
    return temp_database


@pytest.fixture
def conn(migrated: HiddenUrl) -> Iterator[psycopg.Connection]:
    with psycopg.connect(migrated, autocommit=True) as connection:
        yield connection


def add_raw_records(conn: psycopg.Connection, cases: list[dict[str, Any]]) -> dict[str, str]:
    """샘플을 raw_records에 넣고 샘플 이름별 raw id를 돌려준다.

    Args:
        conn: 임시 DB 연결.
        cases: raw.json의 샘플 목록.
    """
    ids = {}
    for case in cases:
        ids[case["case"]] = new_id("raw")
        conn.execute(
            "INSERT INTO raw_records (id, kind, siem_profile, siem_ref, fetched_at, original_text)"
            " VALUES (%s, %s, 'elk-test', %s, %s, %s)",
            (
                ids[case["case"]],
                case["kind"],
                f"{case['original']['_index']}/{case['original']['_id']}",
                to_datetime(1793754000000),
                json.dumps(case["original"], ensure_ascii=True),
            ),
        )
    return ids


def add_assets(conn: psycopg.Connection) -> None:
    """host web-01과 ip 198.51.100.7이 같은 자산(웹서버, 중요도 5)을 가리키게 넣는다.

    Args:
        conn: 임시 DB 연결.
    """
    asset_id = conn.execute(
        "INSERT INTO assets (name, criticality) VALUES ('웹서버', 5) RETURNING asset_id"
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO asset_identifiers (asset_id, entity_type, entity_value)"
        " VALUES (%s, 'host', 'web-01'), (%s, 'ip', '198.51.100.7')",
        (asset_id, asset_id),
    )


def count(conn: psycopg.Connection, table: str) -> int:
    """테이블의 행 수를 센다.

    Args:
        conn: 임시 DB 연결.
        table: 세어 볼 테이블 이름(테스트가 정한 상수).
    """
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]  # noqa: S608


def originals_hash(conn: psycopg.Connection) -> str:
    """raw_records의 모든 원본을 합친 해시를 돌려준다.

    Args:
        conn: 임시 DB 연결.
    """
    rows = conn.execute("SELECT id, original_text FROM raw_records ORDER BY id").fetchall()
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def owner() -> str:
    """새 임대 소유자 값을 만든다."""
    return uuid.uuid4().hex


def test_run_saves_valid_results_and_records_each_failure(conn: psycopg.Connection) -> None:
    ids = add_raw_records(conn, CASES)
    add_assets(conn)
    expected_ok = [case for case in CASES if "error" not in case["expect"]]

    result = run(SETTINGS, conn, owner())

    assert (result.claimed, result.succeeded, result.failed) == (
        len(CASES),
        len(expected_ok),
        len(FAILURES),
    )
    assert result.failures == {code: FAILURES.count(code) for code in set(FAILURES)}
    assert exit_code(result) == 1
    assert count(conn, "alerts") == sum(c["expect"].get("kind") == "alert" for c in expected_ok)
    assert count(conn, "events") == sum(c["expect"].get("kind") == "event" for c in expected_ok)
    status = dict(conn.execute("SELECT raw_id, status FROM normalize_status").fetchall())
    for case in CASES:
        assert status[ids[case["case"]]] == ("failed" if "error" in case["expect"] else "succeeded")
    codes = conn.execute(
        "SELECT error_code FROM normalize_status WHERE status = 'failed' ORDER BY error_code"
    ).fetchall()
    assert [code for (code,) in codes] == sorted(FAILURES)


def test_results_point_back_and_carry_assets(conn: psycopg.Connection) -> None:
    ids = add_raw_records(conn, [c for c in CASES if c["case"] == "alert_flat_keys"])
    add_assets(conn)

    run(SETTINGS, conn, owner())

    raw_id = ids["alert_flat_keys"]
    alert_id, assets = conn.execute(
        "SELECT id, assets FROM alerts WHERE raw_id = %s", (raw_id,)
    ).fetchone()
    assert [asset["entity"] for asset in assets] == [
        {"type": "ip", "value": "198.51.100.7"},
        {"type": "host", "value": "web-01"},
    ]
    assert conn.execute(
        "SELECT result_kind, result_id FROM normalize_status WHERE raw_id = %s", (raw_id,)
    ).fetchone() == ("alert", alert_id)


def test_an_empty_asset_table_is_a_successful_no_match(conn: psycopg.Connection) -> None:
    add_raw_records(conn, [c for c in CASES if c["case"] == "alert_flat_keys"])

    result = run(SETTINGS, conn, owner())

    assert result.succeeded == 1
    assert conn.execute("SELECT assets FROM alerts").fetchone() == ([],)


def test_normalize_does_not_retry_failed_records(conn: psycopg.Connection) -> None:
    add_raw_records(conn, CASES)
    run(SETTINGS, conn, owner())
    alerts, events = count(conn, "alerts"), count(conn, "events")

    second = run(SETTINGS, conn, owner())

    assert (second.claimed, second.succeeded, second.failed) == (0, 0, 0)
    assert (count(conn, "alerts"), count(conn, "events")) == (alerts, events)
    attempts = conn.execute(
        "SELECT DISTINCT attempts FROM normalize_status WHERE status = 'failed'"
    ).fetchall()
    assert attempts == [(1,)]


def test_retry_run_retries_only_failures_and_adds_no_duplicates(conn: psycopg.Connection) -> None:
    add_raw_records(conn, CASES)
    run(SETTINGS, conn, owner())
    alerts, events = count(conn, "alerts"), count(conn, "events")

    second = run_failed(SETTINGS, conn, owner())

    assert (second.claimed, second.succeeded, second.failed) == (len(FAILURES), 0, len(FAILURES))
    assert (count(conn, "alerts"), count(conn, "events")) == (alerts, events)
    attempts = conn.execute(
        "SELECT DISTINCT attempts FROM normalize_status WHERE status = 'failed'"
    ).fetchall()
    assert attempts == [(2,)]


def test_retry_succeeds_after_mapping_is_corrected(
    conn: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    failing = next(c for c in CASES if c["case"] == "alert_without_title")
    raw_id = add_raw_records(conn, [failing])["alert_without_title"]
    before = originals_hash(conn)
    run(SETTINGS, conn, owner())

    def corrected_mapping(raw: RawRow):
        original = dict(raw.original)
        source = {**original["_source"], "kibana.alert.rule.name": "Recovered rule"}
        original["_source"] = source
        return map_normalize(RawRow(raw.id, raw.kind, original))

    monkeypatch.setattr(run_module, "normalize", corrected_mapping)
    result = run_failed(SETTINGS, conn, owner())

    assert (result.claimed, result.succeeded, result.failed) == (1, 1, 0)
    status = conn.execute(
        "SELECT status, attempts, result_kind, result_id FROM normalize_status WHERE raw_id = %s",
        (raw_id,),
    ).fetchone()
    assert status[:3] == ("succeeded", 2, "alert")
    assert status[3] is not None
    assert conn.execute("SELECT count(*) FROM alerts WHERE raw_id = %s", (raw_id,)).fetchone() == (
        1,
    )
    assert originals_hash(conn) == before

    second = run_failed(SETTINGS, conn, owner())
    assert second.claimed == 0
    assert conn.execute("SELECT count(*) FROM alerts WHERE raw_id = %s", (raw_id,)).fetchone() == (
        1,
    )


def test_run_does_not_modify_originals(conn: psycopg.Connection) -> None:
    add_raw_records(conn, CASES)
    before = originals_hash(conn)

    run(SETTINGS, conn, owner())

    assert originals_hash(conn) == before


def test_normalize_processes_pending_while_failed_waits_for_retry(conn: psycopg.Connection) -> None:
    failing = [c for c in CASES if c["case"] == "alert_without_title"]
    failed_id = add_raw_records(conn, failing)["alert_without_title"]
    run(SETTINGS, conn, owner())
    ok = [c for c in CASES if c["case"] == "alert_flat_keys"]
    add_raw_records(conn, ok)
    small = replace(SETTINGS, batch_size=1)

    result = run(small, conn, owner())

    assert (result.claimed, result.succeeded) == (1, 1)
    assert conn.execute(
        "SELECT status, attempts FROM normalize_status WHERE raw_id = %s", (failed_id,)
    ).fetchone() == ("failed", 1)
    new_raw = {
        **ok[0],
        "case": "alert_new",
        "original": {**ok[0]["original"], "_id": "alert-new"},
    }
    new_id = add_raw_records(conn, [new_raw])["alert_new"]
    retry = run_failed(SETTINGS, conn, owner())
    assert (retry.claimed, retry.failed) == (1, 1)
    assert conn.execute(
        "SELECT count(*) FROM normalize_status WHERE raw_id = %s", (new_id,)
    ).fetchone() == (0,)


def test_claimed_records_are_not_given_to_another_worker(
    conn: psycopg.Connection, migrated: HiddenUrl
) -> None:
    add_raw_records(conn, CASES)
    with psycopg.connect(migrated, autocommit=True) as other:
        first = claim_pending_batch(conn, owner(), 200, 600)
        second = claim_pending_batch(other, owner(), 200, 600)

    assert len(first) == len(CASES)
    assert second == []


def expire_lease(conn: psycopg.Connection) -> None:
    """모든 상태 행의 임대를 1초 전에 만료된 것으로 만든다.

    Args:
        conn: 임시 DB 연결.
    """
    conn.execute("UPDATE normalize_status SET lease_expires_at = now() - interval '1 second'")


def test_late_worker_cannot_write_after_losing_its_lease(conn: psycopg.Connection) -> None:
    case = next(c for c in CASES if c["case"] == "alert_flat_keys")
    raw_id = add_raw_records(conn, [case])["alert_flat_keys"]
    late, current = owner(), owner()
    claim_pending_batch(conn, late, 200, 600)
    expire_lease(conn)
    assert [raw.id for raw in claim_pending_batch(conn, current, 200, 600)] == [raw_id]
    row = {"id": new_id("alt")}

    late_saved = save_success(conn, late, raw_id, "alert", row)
    late_failed = save_failure(conn, late, raw_id, "db_error")

    assert (late_saved, late_failed) == (False, False)
    assert count(conn, "alerts") == 0
    assert conn.execute(
        "SELECT status, lease_owner FROM normalize_status WHERE raw_id = %s", (raw_id,)
    ).fetchone() == ("pending", current)


def test_late_retry_worker_cannot_write_after_losing_its_lease(
    conn: psycopg.Connection,
) -> None:
    failing = [c for c in CASES if c["case"] == "alert_without_title"]
    raw_id = add_raw_records(conn, failing)["alert_without_title"]
    run(SETTINGS, conn, owner())
    late, current = owner(), owner()
    assert [raw.id for raw in claim_failed_batch(conn, late, 200, 600)] == [raw_id]
    expire_lease(conn)
    assert [raw.id for raw in claim_failed_batch(conn, current, 200, 600)] == [raw_id]

    late_saved = save_success(conn, late, raw_id, "alert", {"id": new_id("alt")})
    late_failed = save_failure(conn, late, raw_id, "db_error")

    assert (late_saved, late_failed) == (False, False)
    assert count(conn, "alerts") == 0
    assert conn.execute(
        "SELECT status, lease_owner FROM normalize_status WHERE raw_id = %s", (raw_id,)
    ).fetchone() == ("failed", current)


def test_failure_cannot_overwrite_a_success(conn: psycopg.Connection) -> None:
    add_raw_records(conn, [c for c in CASES if c["case"] == "alert_flat_keys"])
    first = owner()
    run(SETTINGS, conn, first)

    recorded = save_failure(
        conn, first, conn.execute("SELECT raw_id FROM normalize_status").fetchone()[0], "db_error"
    )

    assert recorded is False
    assert conn.execute("SELECT status FROM normalize_status").fetchone() == ("succeeded",)


def test_result_is_not_saved_when_the_insert_fails(conn: psycopg.Connection) -> None:
    case = next(c for c in CASES if c["case"] == "alert_flat_keys")
    raw_id = add_raw_records(conn, [case])["alert_flat_keys"]
    me = owner()
    claim_pending_batch(conn, me, 200, 600)
    broken = {"id": new_id("alt"), "raw_id": raw_id}

    with pytest.raises((KeyError, psycopg.Error)):
        save_success(conn, me, raw_id, "alert", broken)

    assert count(conn, "alerts") == 0
    assert conn.execute("SELECT status FROM normalize_status").fetchone() == ("pending",)


def test_asset_lookup_failure_is_recorded_and_nothing_is_saved(
    conn: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_raw_records(conn, [c for c in CASES if c["case"] == "alert_flat_keys"])

    def fail(*args: Any) -> None:
        raise AssetLookupError

    monkeypatch.setattr(run_module, "lookup_assets", fail)

    result = run(SETTINGS, conn, owner())

    assert result.failures == {"asset_lookup_failed": 1}
    assert count(conn, "alerts") == 0


def test_database_error_while_saving_is_recorded_as_db_error(
    conn: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_raw_records(conn, [c for c in CASES if c["case"] == "alert_flat_keys"])

    def fail(*args: Any) -> bool:
        raise psycopg.errors.CheckViolation

    monkeypatch.setattr(run_module, "save_success", fail)

    result = run(SETTINGS, conn, owner())

    assert result.failures == {"db_error": 1}


def test_colliding_escaped_keys_are_recorded_as_escape_collision(
    conn: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    raw_id = add_raw_records(conn, [c for c in CASES if c["case"] == "alert_flat_keys"])[
        "alert_flat_keys"
    ]

    def colliding(raw: RawRow):
        mapped = map_normalize(raw)
        return replace(mapped, row={**mapped.row, "details": {"a\x00": 1, "a\\u0000": 2}})

    monkeypatch.setattr(run_module, "normalize", colliding)
    result = run(SETTINGS, conn, owner())

    assert result.failures == {"escape_collision": 1}
    assert conn.execute(
        "SELECT status, error_code FROM normalize_status WHERE raw_id = %s", (raw_id,)
    ).fetchone() == ("failed", "escape_collision")
    assert count(conn, "alerts") == 0


def test_non_colliding_nul_keys_still_succeed_in_the_db(
    conn: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    add_raw_records(conn, [c for c in CASES if c["case"] == "alert_flat_keys"])

    def with_nul_keys(raw: RawRow):
        mapped = map_normalize(raw)
        return replace(mapped, row={**mapped.row, "details": {"a\x00": 1, "b\x00": 2}})

    monkeypatch.setattr(run_module, "normalize", with_nul_keys)
    result = run(SETTINGS, conn, owner())

    assert (result.succeeded, result.failed) == (1, 0)
    assert count(conn, "alerts") == 1


def test_asset_lookup_matches_by_type_and_value(conn: psycopg.Connection) -> None:
    add_assets(conn)
    conn.execute("INSERT INTO assets (name) VALUES (NULL)")

    found = lookup_assets(
        conn,
        [
            {"type": "host", "value": "WEB-01"},
            {"type": "user", "value": "web-01"},
            {"type": "ip", "value": "198.51.100.7"},
        ],
        SETTINGS.asset_statement_timeout_ms,
    )

    assert [(a["entity"]["type"], a["name"], a["criticality"], a["owner"]) for a in found] == [
        ("host", "웹서버", 5, None),
        ("ip", "웹서버", 5, None),
    ]


def test_asset_lookup_fails_when_the_table_is_missing(conn: psycopg.Connection) -> None:
    conn.execute("DROP TABLE asset_identifiers")

    with pytest.raises(AssetLookupError):
        lookup_assets(conn, [{"type": "host", "value": "web-01"}], 5000)


def test_asset_identifiers_are_unique_per_type_and_value(conn: psycopg.Connection) -> None:
    add_assets(conn)
    other = conn.execute("INSERT INTO assets (name) VALUES ('다른') RETURNING asset_id").fetchone()[
        0
    ]

    with pytest.raises(psycopg.errors.UniqueViolation):
        conn.execute(
            "INSERT INTO asset_identifiers (asset_id, entity_type, entity_value)"
            " VALUES (%s, 'host', 'web-01')",
            (other,),
        )


def test_status_row_requires_a_result_exactly_when_succeeded(conn: psycopg.Connection) -> None:
    raw_id = add_raw_records(conn, CASES[:1])[CASES[0]["case"]]

    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute(
            "INSERT INTO normalize_status (raw_id, status) VALUES (%s, 'succeeded')", (raw_id,)
        )
