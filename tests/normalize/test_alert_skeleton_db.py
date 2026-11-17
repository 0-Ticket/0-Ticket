"""Alert 정규화 뼈대(#326)의 결과 기록·폴백·점검 명령을 임시 DB에서 확인한다(db 마커)."""

import hashlib
import json
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest
from conftest import HiddenUrl

from soc.asset_lookup import AssetLookupError
from soc.contracts import to_datetime, to_epoch_ms
from soc.db.migrate import migrate
from soc.ids import new_id
from soc.l1.ticketing import run as run_ticketing
from soc.normalize import run as run_module
from soc.normalize.__main__ import main
from soc.normalize.config import Settings
from soc.normalize.errors import NormalizeError
from soc.normalize.report import report_lines
from soc.normalize.run import run, run_failed
from soc.ticketing import TicketingPolicy

pytestmark = pytest.mark.db

ROOT = Path(__file__).parent.parent / "fixtures" / "normalize"
ALERTS = json.loads((ROOT / "alert_skeleton.json").read_text(encoding="utf-8"))
EVENT = next(
    case
    for case in json.loads((ROOT / "raw.json").read_text(encoding="utf-8"))
    if case["kind"] == "event"
)
FETCHED_AT = to_epoch_ms(datetime.fromisoformat("2026-11-13T01:00:00+00:00"))
SETTINGS = Settings(
    batch_size=200, lease_seconds=600, connect_timeout_seconds=5, asset_statement_timeout_ms=5000
)


@pytest.fixture
def conn(temp_database: HiddenUrl) -> Iterator[psycopg.Connection]:
    migrate(temp_database)
    with psycopg.connect(temp_database, autocommit=True) as connection:
        yield connection


def add_raw(
    conn: psycopg.Connection, cases: list[dict[str, Any]], kind: str = "alert"
) -> dict[str, str]:
    """샘플을 raw_records에 넣고 샘플 이름별 raw id를 돌려준다."""
    ids = {}
    for case in cases:
        ids[case["case"]] = new_id("raw")
        conn.execute(
            "INSERT INTO raw_records (id, kind, siem_profile, siem_ref, fetched_at, original_text)"
            " VALUES (%s, %s, 'elk-test', %s, %s, %s)",
            (
                ids[case["case"]],
                kind,
                f"skeleton/{case['case']}",
                to_datetime(FETCHED_AT),
                json.dumps(case["original"], ensure_ascii=True),
            ),
        )
    return ids


def status_of(conn: psycopg.Connection, raw_id: str) -> tuple[Any, ...]:
    """normalize_status 한 행의 (status, error_code, outcome, missing_fields, source)."""
    return conn.execute(
        "SELECT status, error_code, outcome, missing_fields, source FROM normalize_status"
        " WHERE raw_id = %s",
        (raw_id,),
    ).fetchone()


def originals_hash(conn: psycopg.Connection) -> str:
    rows = conn.execute("SELECT id, original_text FROM raw_records ORDER BY id").fetchall()
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def test_every_sample_is_stored_with_its_outcome_and_the_original_is_untouched(
    conn: psycopg.Connection,
) -> None:
    ids = add_raw(conn, ALERTS)
    before = originals_hash(conn)

    result = run(SETTINGS, conn, "owner-1")

    assert (result.claimed, result.succeeded, result.failed) == (len(ALERTS), len(ALERTS), 0)
    for case in ALERTS:
        expect = case["expect"]
        status, error_code, outcome, missing, source = status_of(conn, ids[case["case"]])
        assert (status, error_code, outcome, source) == (
            "succeeded",
            expect["error_code"],
            expect["outcome"],
            expect["source"],
        ), case["case"]
        assert missing == expect.get("missing_fields", []), case["case"]
    kinds = conn.execute("SELECT DISTINCT result_kind FROM normalize_status").fetchall()
    assert kinds == [("alert",)]
    assert conn.execute(
        "SELECT count(*) FROM alerts WHERE (ocsf->>'class_uid')::int = 0"
    ).fetchone()[0] == sum(case["expect"]["outcome"] == "fallback" for case in ALERTS)
    assert originals_hash(conn) == before


def test_events_keep_null_outcome_and_source(conn: psycopg.Connection) -> None:
    ids = add_raw(conn, [EVENT], kind="event")

    run(SETTINGS, conn, "owner-1")

    assert status_of(conn, ids[EVENT["case"]]) == ("succeeded", None, None, [], None)


def test_a_mapping_that_fails_validation_is_kept_as_a_fallback_alert(
    conn: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = add_raw(conn, ALERTS[:1])
    real = run_module.validate_ocsf

    def reject_findings(ocsf: dict[str, Any]) -> None:
        if ocsf["class_uid"] == 2004:
            raise NormalizeError("schema_failed")
        real(ocsf)

    monkeypatch.setattr(run_module, "validate_ocsf", reject_findings)

    result = run(SETTINGS, conn, "owner-1")

    assert (result.succeeded, result.failed) == (1, 0)
    assert status_of(conn, ids[ALERTS[0]["case"]])[:3] == (
        "succeeded",
        "validation_failed",
        "fallback",
    )
    assert conn.execute("SELECT details FROM alerts").fetchone() == (
        {"fallback": {"reason": "validation_failed"}},
    )


def test_transient_lookup_errors_stay_failed_and_are_retried(
    conn: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    ids = add_raw(conn, ALERTS[:1])

    def broken(*args: Any, **kwargs: Any) -> Any:
        raise AssetLookupError

    monkeypatch.setattr(run_module, "lookup_assets", broken)
    first = run(SETTINGS, conn, "owner-1")
    monkeypatch.undo()
    retried = run_failed(SETTINGS, conn, "owner-2")

    assert (first.failed, first.failures) == (1, {"asset_lookup_failed": 1})
    assert (retried.succeeded, retried.failed) == (1, 0)
    assert status_of(conn, ids[ALERTS[0]["case"]])[:3] == ("succeeded", None, "ok")


@pytest.mark.parametrize(
    ("policy", "triage_status", "tickets"),
    [(TicketingPolicy("auto", ()), None, 1), (TicketingPolicy("scenario", ()), "pending", 0)],
    ids=["auto-creates-a-ticket", "scenario-marks-pending-for-l1"],
)
def test_a_fallback_alert_goes_through_the_ticket_branch(
    conn: psycopg.Connection, policy: TicketingPolicy, triage_status: str | None, tickets: int
) -> None:
    fallback = next(case for case in ALERTS if case["case"] == "fallback_missing_title")
    add_raw(conn, [fallback])
    run(SETTINGS, conn, "owner-1")

    result = run_ticketing(conn, policy, clock=lambda: FETCHED_AT)

    assert result.failed == 0
    assert conn.execute("SELECT count(*) FROM tickets").fetchone() == (tickets,)
    assert conn.execute("SELECT triage ->> 'status' FROM alerts").fetchone() == (triage_status,)


def test_report_counts_outcomes_and_missing_fields_per_source(conn: psycopg.Connection) -> None:
    add_raw(conn, ALERTS)
    add_raw(conn, [EVENT], kind="event")
    run(SETTINGS, conn, "owner-1")

    lines = report_lines(conn)

    assert "suricata total=6 ok=4 partial=2 fallback=0" in lines
    assert "suricata missing finding_info.analytic.uid=1/6" in lines
    assert "suricata missing start_time=2/6" in lines
    assert "unknown total=6 ok=0 partial=1 fallback=5" in lines
    assert not any("web" in line or "event" in line for line in lines)


def test_report_command_prints_the_lines(
    conn: psycopg.Connection,
    temp_database: HiddenUrl,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    add_raw(conn, ALERTS[:1])
    run(SETTINGS, conn, "owner-1")
    monkeypatch.setenv("DATABASE_URL", temp_database)

    assert main(["report"]) == 0
    assert "suricata total=1 ok=1 partial=0 fallback=0" in capsys.readouterr().out
    assert main(["unknown"]) == 2


def test_the_outcome_column_only_takes_known_values(conn: psycopg.Connection) -> None:
    raw_id = add_raw(conn, ALERTS[:1])[ALERTS[0]["case"]]
    conn.execute("INSERT INTO normalize_status (raw_id) VALUES (%s)", (raw_id,))

    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE normalize_status SET outcome = 'great'")
    with pytest.raises(psycopg.errors.CheckViolation):
        conn.execute("UPDATE normalize_status SET source = 'snort'")
