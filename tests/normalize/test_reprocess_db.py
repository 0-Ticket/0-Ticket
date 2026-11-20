"""기존 알럿 재처리(#334)를 임시 DB에서 확인한다(db 마커).

옛 형식 알럿은 새 로직으로 정규화한 뒤 정규화 컬럼을 일부러 낡은 값으로 바꿔 만든다.
원본은 tests/fixtures/normalize/alert_skeleton.json의 손으로 만든 샘플이다.
"""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest
from conftest import HiddenUrl

from soc.contracts import to_datetime
from soc.db.migrate import migrate
from soc.ids import new_id
from soc.normalize import run as run_module
from soc.normalize.config import Settings
from soc.normalize.reprocess import exit_code, format_result, reprocess
from soc.normalize.run import run

pytestmark = pytest.mark.db

ROOT = Path(__file__).parent.parent / "fixtures" / "normalize"
ALERTS = json.loads((ROOT / "alert_skeleton.json").read_text(encoding="utf-8"))
EVENT = next(
    case
    for case in json.loads((ROOT / "raw.json").read_text(encoding="utf-8"))
    if case["kind"] == "event"
)
SETTINGS = Settings(
    batch_size=200, lease_seconds=600, connect_timeout_seconds=5, asset_statement_timeout_ms=5000
)
SQLI = "modsecurity_sqli_keeps_cookie_out"
XSS = "modsecurity_xss_attack_tags_dedupe"
LFI = "suricata_lfi"
REACT = "suricata_react2shell_flat_and_nested"
OLD_TITLE = "old title"


IDS: dict[str, str] = {}


def raw_id_of(name: str) -> str:
    """add_raw가 샘플 이름에 붙인 raw id."""
    return IDS[name]


@pytest.fixture
def conn(temp_database: HiddenUrl) -> Iterator[psycopg.Connection]:
    migrate(temp_database)
    with psycopg.connect(temp_database, autocommit=True) as connection:
        yield connection


def add_raw(conn: psycopg.Connection, cases: list[dict[str, Any]], kind: str = "alert") -> None:
    for case in cases:
        IDS[case["case"]] = new_id("raw")
        conn.execute(
            "INSERT INTO raw_records (id, kind, siem_profile, siem_ref, fetched_at, original_text)"
            " VALUES (%s, %s, 'elk-test', %s, %s, %s)",
            (
                raw_id_of(case["case"]),
                kind,
                f"reprocess/{case['case']}",
                to_datetime(1793754000000),
                json.dumps(case["original"], ensure_ascii=True),
            ),
        )


def seed(conn: psycopg.Connection, *names: str) -> list[str]:
    """샘플을 새 로직으로 정규화해 알럿으로 넣고 raw id 목록을 돌려준다."""
    add_raw(conn, [next(c for c in ALERTS if c["case"] == name) for name in names])
    run(SETTINGS, conn, "seed")
    return [raw_id_of(name) for name in names]


def age(conn: psycopg.Connection, raw_id: str) -> None:
    """정규화 컬럼을 낡은 값으로 바꾸고 outcome·source를 비워 #326 이전 행처럼 만든다."""
    conn.execute(
        "UPDATE alerts SET title = %s, severity = 1, rule_id = 'old-rule', entities = '[]',"
        " ocsf = '{}', details = '{}', time = time - interval '1 hour' WHERE raw_id = %s",
        (OLD_TITLE, raw_id),
    )
    conn.execute(
        "UPDATE normalize_status SET outcome = NULL, source = NULL, missing_fields = '{}',"
        " error_code = NULL WHERE raw_id = %s",
        (raw_id,),
    )


def alert_row(conn: psycopg.Connection, raw_id: str) -> tuple[Any, ...]:
    return conn.execute(
        "SELECT id, raw_id, time, severity, title, rule_id, entities, assets, triage, ocsf, details"
        " FROM alerts WHERE raw_id = %s ORDER BY id LIMIT 1",
        (raw_id,),
    ).fetchone()


def status_row(conn: psycopg.Connection, raw_id: str) -> tuple[Any, ...]:
    return conn.execute(
        "SELECT status, result_kind, result_id, outcome, source, missing_fields, error_code,"
        " attempts FROM normalize_status WHERE raw_id = %s",
        (raw_id,),
    ).fetchone()


def dump(conn: psycopg.Connection) -> dict[str, list[tuple[Any, ...]]]:
    return {
        table: conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
        for table in ("raw_records", "alerts", "events", "normalize_status", "tickets")
    }


def add_ticket(conn: psycopg.Connection, alert_id: str) -> None:
    now = to_datetime(1793754000000)
    conn.execute(
        "INSERT INTO tickets (id, origin, status, alert_ids, entities, created_at, updated_at,"
        " details) VALUES (%s, 'auto', 'new', %s, '[]', %s, %s, '{}')",
        (new_id("tkt"), [alert_id], now, now),
    )


def test_updates_normalized_columns_and_keeps_identity_triage_and_tickets(
    conn: psycopg.Connection,
) -> None:
    raws = seed(conn, SQLI, LFI)
    for raw_id in raws:
        conn.execute(
            'UPDATE alerts SET triage = \'{"status": "pending"}\' WHERE raw_id = %s', (raw_id,)
        )
        add_ticket(conn, alert_row(conn, raw_id)[0])
    expected = {raw_id: alert_row(conn, raw_id) for raw_id in raws}
    expected_status = {raw_id: status_row(conn, raw_id) for raw_id in raws}
    for raw_id in raws:
        age(conn, raw_id)
    counts_before = [
        conn.execute(f"SELECT count(*) FROM {t}").fetchone() for t in ("alerts", "tickets")
    ]
    tickets_before = conn.execute("SELECT * FROM tickets ORDER BY id").fetchall()

    result = reprocess(SETTINGS, conn)

    assert (result.read, result.changed, result.errors) == (2, 2, 0)
    for raw_id in raws:
        assert alert_row(conn, raw_id) == expected[raw_id]
        # attempts는 그대로이고 outcome·source·missing_fields·error_code만 새 값이다
        assert status_row(conn, raw_id) == expected_status[raw_id]
    assert [
        conn.execute(f"SELECT count(*) FROM {t}").fetchone() for t in ("alerts", "tickets")
    ] == (counts_before)
    assert conn.execute("SELECT * FROM tickets ORDER BY id").fetchall() == tickets_before
    assert result.by_source["modsecurity"]["changed"] == 1
    assert result.by_source["suricata"]["changed"] == 1


def test_second_run_changes_nothing(conn: psycopg.Connection) -> None:
    raws = seed(conn, SQLI, LFI)
    for raw_id in raws:
        age(conn, raw_id)
    reprocess(SETTINGS, conn)
    before = dump(conn)

    default_again = reprocess(SETTINGS, conn)
    by_source = reprocess(SETTINGS, conn, source="modsecurity")
    everything = reprocess(SETTINGS, conn, source="suricata")

    assert default_again.read == 0
    assert (by_source.read, by_source.changed, by_source.unchanged) == (2, 0, 1)
    assert (everything.changed, everything.unchanged) == (0, 1)
    assert dump(conn) == before


def test_dry_run_writes_nothing_and_prints_only_counts(conn: psycopg.Connection) -> None:
    raws = seed(conn, SQLI)
    entities = alert_row(conn, raws[0])[6]
    age(conn, raws[0])
    before = dump(conn)

    result = reprocess(SETTINGS, conn, dry_run=True)

    assert dump(conn) == before
    assert result.changed == 1
    assert {"title", "entities", "ocsf"} <= set(result.columns)
    assert result.entity_changes["+ip/dst"] >= 1
    text = format_result(result)
    assert "would_update=1" in text
    assert OLD_TITLE not in text
    assert all(str(entity["value"]) not in text for entity in entities)


def test_fallback_result_is_skipped_and_counted(conn: psycopg.Connection) -> None:
    raws = seed(conn, "fallback_missing_title")
    age(conn, raws[0])
    before = (alert_row(conn, raws[0]), status_row(conn, raws[0]))

    result = reprocess(SETTINGS, conn)

    assert (result.read, result.changed, result.skipped) == (1, 0, {"fallback": 1})
    assert (alert_row(conn, raws[0]), status_row(conn, raws[0])) == before
    assert "fallback=1" in format_result(result)
    assert exit_code(result) == 0


def test_lower_outcome_is_skipped_and_same_outcome_is_updated(conn: psycopg.Connection) -> None:
    raws = seed(conn, "unknown_source_is_partial")
    age(conn, raws[0])
    conn.execute(
        "UPDATE normalize_status SET outcome = 'ok', source = 'unknown' WHERE raw_id = %s", raws
    )
    before = (alert_row(conn, raws[0]), status_row(conn, raws[0]))

    skipped = reprocess(SETTINGS, conn, source="unknown")

    assert (skipped.changed, skipped.skipped) == (0, {"worse": 1})
    assert (alert_row(conn, raws[0]), status_row(conn, raws[0])) == before

    conn.execute("UPDATE normalize_status SET outcome = 'partial' WHERE raw_id = %s", raws)
    updated = reprocess(SETTINGS, conn, source="unknown")

    assert (updated.changed, updated.skipped) == (1, {})
    assert alert_row(conn, raws[0])[4] != OLD_TITLE
    assert status_row(conn, raws[0])[3] == "partial"


def test_default_targets_only_rows_without_outcome(conn: psycopg.Connection) -> None:
    sqli, lfi = seed(conn, SQLI, LFI)
    age(conn, sqli)
    age(conn, lfi)
    # #326 이후 #332 이전에 처리된 행: outcome은 ok인데 dst가 없다
    conn.execute(
        "UPDATE normalize_status SET outcome = 'ok', source = 'modsecurity' WHERE raw_id = %s",
        (sqli,),
    )

    result = reprocess(SETTINGS, conn)

    assert (result.read, result.changed) == (1, 1)
    assert alert_row(conn, lfi)[4] != OLD_TITLE
    assert alert_row(conn, sqli)[4] == OLD_TITLE


def test_source_filter_uses_new_source_and_updates_rows_with_outcome(
    conn: psycopg.Connection,
) -> None:
    sqli, lfi = seed(conn, SQLI, LFI)
    age(conn, sqli)
    age(conn, lfi)
    conn.execute(
        "UPDATE normalize_status SET outcome = 'ok', source = 'modsecurity' WHERE raw_id = %s",
        (sqli,),
    )

    suricata = reprocess(SETTINGS, conn, source="suricata")  # 저장된 source가 NULL인 옛 행

    assert (suricata.read, suricata.changed, suricata.other_source) == (2, 1, 1)
    assert alert_row(conn, lfi)[4] != OLD_TITLE
    assert alert_row(conn, sqli)[4] == OLD_TITLE

    modsecurity = reprocess(SETTINGS, conn, source="modsecurity")  # outcome이 이미 있는 행

    assert (modsecurity.changed, modsecurity.other_source) == (1, 1)
    assert alert_row(conn, sqli)[4] != OLD_TITLE
    assert status_row(conn, sqli)[3:5] == ("ok", "modsecurity")


def test_all_option_reads_rows_that_already_have_an_outcome(conn: psycopg.Connection) -> None:
    (raw_id,) = seed(conn, SQLI)
    conn.execute("UPDATE alerts SET ocsf = ocsf - 'evidences' WHERE raw_id = %s", (raw_id,))
    before = alert_row(conn, raw_id)

    by_default = reprocess(SETTINGS, conn)
    everything = reprocess(SETTINGS, conn, all_rows=True)

    assert by_default.read == 0
    assert (everything.read, everything.changed) == (1, 1)
    after = alert_row(conn, raw_id)
    assert after[0] == before[0]  # 알럿 id는 그대로
    assert "evidences" in after[9]


def test_event_rows_are_not_touched_by_alert_reprocess(conn: psycopg.Connection) -> None:
    seed(conn, SQLI)
    add_raw(conn, [EVENT], kind="event")
    run(SETTINGS, conn, "events")
    age(conn, raw_id_of(SQLI))
    event_status = conn.execute(
        "SELECT * FROM normalize_status WHERE result_kind = 'event' ORDER BY raw_id"
    ).fetchall()
    events = conn.execute("SELECT * FROM events ORDER BY id").fetchall()
    assert event_status
    assert events

    by_default = reprocess(SETTINGS, conn)
    by_source = reprocess(SETTINGS, conn, source="unknown")

    assert by_default.read == 1
    assert by_source.read == 1
    assert (
        conn.execute(
            "SELECT * FROM normalize_status WHERE result_kind = 'event' ORDER BY raw_id"
        ).fetchall()
        == event_status
    )
    assert conn.execute("SELECT * FROM events ORDER BY id").fetchall() == events


def test_other_alerts_of_same_raw_are_reported_not_updated(conn: psycopg.Connection) -> None:
    (raw_id,) = seed(conn, SQLI)
    age(conn, raw_id)
    conn.execute(
        "INSERT INTO alerts (id, raw_id, time, severity, title, rule_id, entities, assets, ocsf,"
        " details) SELECT 'alt_duplicate', raw_id, time, severity, title, rule_id, entities,"
        " assets, ocsf, details FROM alerts WHERE raw_id = %s",
        (raw_id,),
    )
    duplicate = conn.execute("SELECT * FROM alerts WHERE id = 'alt_duplicate'").fetchone()

    result = reprocess(SETTINGS, conn)

    assert (result.changed, result.duplicates) == (1, 1)
    assert conn.execute("SELECT * FROM alerts WHERE id = 'alt_duplicate'").fetchone() == duplicate
    assert alert_row(conn, raw_id)[0] != "alt_duplicate"


def test_db_error_rolls_back_only_that_row_and_exits_with_1(
    conn: psycopg.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    xss, sqli = seed(conn, XSS, SQLI)
    age(conn, xss)
    age(conn, sqli)
    before = (alert_row(conn, xss), status_row(conn, xss))
    real = run_module.lookup_assets
    calls = []

    def flaky(*args: Any) -> Any:
        calls.append(1)
        if len(calls) == 1:
            raise psycopg.errors.DataError
        return real(*args)

    monkeypatch.setattr(run_module, "lookup_assets", flaky)

    result = reprocess(SETTINGS, conn)

    assert (result.read, result.changed, result.errors) == (2, 1, 1)
    assert exit_code(result) == 1
    assert (alert_row(conn, xss), status_row(conn, xss)) == before  # 시각순 첫 행이 실패한다
    assert alert_row(conn, sqli)[4] != OLD_TITLE


def test_limit_counts_read_rows_in_time_then_id_order_and_since_uses_alert_time(
    conn: psycopg.Connection,
) -> None:
    raws = seed(conn, SQLI, LFI, REACT, XSS)  # 시각순: XSS, REACT, LFI, SQLI
    for raw_id in raws:
        age(conn, raw_id)

    limited = reprocess(SETTINGS, conn, limit=2)

    assert (limited.read, limited.changed) == (2, 2)
    assert alert_row(conn, raw_id_of(XSS))[4] != OLD_TITLE
    assert alert_row(conn, raw_id_of(REACT))[4] != OLD_TITLE
    assert alert_row(conn, raw_id_of(LFI))[4] == OLD_TITLE
    assert alert_row(conn, raw_id_of(SQLI))[4] == OLD_TITLE

    since = reprocess(SETTINGS, conn, since=datetime(2026, 11, 13, tzinfo=UTC))

    assert (since.read, since.changed) == (2, 2)
    assert alert_row(conn, raw_id_of(LFI))[4] != OLD_TITLE
    assert alert_row(conn, raw_id_of(SQLI))[4] != OLD_TITLE


# --- 이벤트 재처리(#347, D-068) ---
EVENT_CASES = [
    c
    for c in json.loads((ROOT / "raw.json").read_text(encoding="utf-8"))
    if c["kind"] == "event" and "error" not in c["expect"]
]
UNKNOWN_METHOD = "web_unlisted_method"


def seed_events(conn: psycopg.Connection, *names: str) -> list[str]:
    """샘플을 새 로직으로 정규화해 이벤트로 넣고 raw id 목록을 돌려준다."""
    add_raw(conn, [next(c for c in EVENT_CASES if c["case"] == n) for n in names], kind="event")
    run(SETTINGS, conn, "seed")
    return [raw_id_of(name) for name in names]


def age_event(conn: psycopg.Connection, raw_id: str) -> None:
    """#347 이전 행처럼 만든다: ocsf에 message·activity_name이 없고 시각 컬럼이 어긋난다."""
    conn.execute(
        "UPDATE events SET ocsf = ocsf - 'message' - 'activity_name', entities = '[]',"
        " summary = 'old summary' WHERE raw_id = %s",
        (raw_id,),
    )


def event_row(conn: psycopg.Connection, raw_id: str) -> tuple[Any, ...]:
    return conn.execute(
        "SELECT id, raw_id, time, ocsf_class, summary, entities, assets, ocsf, details"
        " FROM events WHERE raw_id = %s ORDER BY id LIMIT 1",
        (raw_id,),
    ).fetchone()


def test_event_reprocess_keeps_id_and_fills_message_and_activity_name(
    conn: psycopg.Connection,
) -> None:
    (raw_id,) = seed_events(conn, UNKNOWN_METHOD)
    before = event_row(conn, raw_id)
    age_event(conn, raw_id)
    status_before = status_row(conn, raw_id)

    result = reprocess(SETTINGS, conn, kind="event")

    after = event_row(conn, raw_id)
    assert (result.kind, result.read, result.changed, result.unchanged) == ("event", 1, 1, 0)
    assert after[0] == before[0]  # 이벤트 id는 그대로
    assert after[2:] == before[2:]  # 새 로직의 결과와 같아진다
    assert after[7]["message"] == "BREW / 200" and after[7]["activity_name"] == "BREW"
    assert status_row(conn, raw_id) == status_before  # normalize_status는 건드리지 않는다
    assert set(result.columns) == {"summary", "ocsf"}  # 이 샘플은 엔티티가 없다
    assert result.by_source == {"class_4002": {"changed": 1, "unchanged": 0, "skipped": 0}}


@pytest.mark.parametrize("source", ["nginx", "modsecurity"])
def test_event_reprocess_reclassifies_filebeat_base_event(
    conn: psycopg.Connection, source: str
) -> None:
    original = json.loads((ROOT / "events" / f"{source}.json").read_text(encoding="utf-8"))
    legacy_source = {
        **original["_source"],
        "event": {"dataset": original["_source"]["event"]["dataset"]},
    }
    legacy_original = {**original, "_source": legacy_source}
    add_raw(conn, [{"case": source, "original": legacy_original}], kind="event")
    run(SETTINGS, conn, "seed")
    raw_id = raw_id_of(source)
    before = event_row(conn, raw_id)
    assert before[3] == before[7]["class_uid"] == 0
    assert any(entity["type"] == "host" for entity in before[5])

    conn.execute(
        "UPDATE raw_records SET original_text = %s WHERE id = %s",
        (json.dumps(original), raw_id),
    )
    status_before = status_row(conn, raw_id)

    result = reprocess(SETTINGS, conn, kind="event")

    after = event_row(conn, raw_id)
    assert (result.kind, result.read, result.changed, result.unchanged) == ("event", 1, 1, 0)
    assert after[:2] == before[:2]
    assert after[2] == datetime(2026, 11, 19, 15, 49, 58, tzinfo=UTC)
    assert after[3] == after[7]["class_uid"] == 4002
    assert after[4] == "GET /catalog 200"
    assert all(entity["type"] != "host" for entity in after[5])
    assert status_row(conn, raw_id) == status_before
    assert conn.execute("SELECT count(*) FROM events WHERE raw_id = %s", (raw_id,)).fetchone() == (
        1,
    )


def test_event_reprocess_second_run_changes_nothing_and_dry_run_writes_nothing(
    conn: psycopg.Connection,
) -> None:
    (raw_id,) = seed_events(conn, UNKNOWN_METHOD)
    age_event(conn, raw_id)
    aged = dump(conn)

    dry = reprocess(SETTINGS, conn, kind="event", dry_run=True)

    assert (dry.changed, dry.dry_run) == (1, True)
    assert dump(conn) == aged
    assert "dry-run read=1 would_update=1" in format_result(dry)
    assert "duplicate_events=0" in format_result(dry)

    assert reprocess(SETTINGS, conn, kind="event").changed == 1
    again = reprocess(SETTINGS, conn, kind="event")
    assert (again.changed, again.unchanged) == (0, 1)


def test_event_reprocess_leaves_alerts_and_alert_reprocess_leaves_events(
    conn: psycopg.Connection,
) -> None:
    (alert_raw,) = seed(conn, SQLI)
    (event_raw,) = seed_events(conn, UNKNOWN_METHOD)
    age(conn, alert_raw)
    age_event(conn, event_raw)
    alerts, events = alert_row(conn, alert_raw), event_row(conn, event_raw)

    reprocess(SETTINGS, conn, kind="event")
    assert alert_row(conn, alert_raw) == alerts  # 알럿은 그대로다
    assert event_row(conn, event_raw) != events

    age_event(conn, event_raw)
    aged_events = event_row(conn, event_raw)
    by_default = reprocess(SETTINGS, conn)  # 기본은 알럿이다
    assert by_default.kind == "alert" and by_default.read == 1
    assert event_row(conn, event_raw) == aged_events


def test_event_reprocess_rejects_source_and_unknown_kind(conn: psycopg.Connection) -> None:
    for kwargs in ({"kind": "event", "source": "suricata"}, {"kind": "log"}):
        with pytest.raises(ValueError):
            reprocess(SETTINGS, conn, **kwargs)


def test_event_reprocess_skips_rows_it_cannot_normalize_and_counts_them(
    conn: psycopg.Connection,
) -> None:
    (raw_id,) = seed_events(conn, UNKNOWN_METHOD)
    conn.execute(
        "UPDATE raw_records SET original_text = %s WHERE id = %s",
        (json.dumps({"_index": "logs-nginx.access-x", "_id": "x"}), raw_id),
    )
    before = event_row(conn, raw_id)

    result = reprocess(SETTINGS, conn, kind="event")

    assert result.skipped == {"validation_failed": 1} and result.changed == 0
    assert event_row(conn, raw_id) == before


def test_event_reprocess_since_and_limit_select_rows(conn: psycopg.Connection) -> None:
    names = ("web_nested_fields", "web_flat_keys", "cloud_read_call")
    for raw_id in seed_events(conn, *names):
        age_event(conn, raw_id)

    assert reprocess(SETTINGS, conn, kind="event", limit=2, dry_run=True).read == 2
    future = datetime(2100, 1, 1, tzinfo=UTC)
    assert reprocess(SETTINGS, conn, kind="event", since=future, dry_run=True).read == 0
    assert reprocess(SETTINGS, conn, kind="event").read == 3
