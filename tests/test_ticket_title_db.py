"""Ticket 제목: 마이그레이션 0109 백필·CHECK와 단발 분기의 폴백(#343, D-067)."""

import re
import shutil
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from conftest import HiddenUrl
from psycopg.types.json import Jsonb
from test_ticket_title import CASES, CLEAN, expand
from test_ticketing_db import NOW_MS, seed_cases

from soc.contracts import to_datetime
from soc.db.migrate import MIGRATIONS_DIR, migrate
from soc.l1.ticketing import run
from soc.ticketing import FALLBACK_TITLE, TITLE_SPACES, TicketingPolicy, clean_title

pytestmark = pytest.mark.db

MIGRATION = MIGRATIONS_DIR / "0109_ticket_title.sql"
NOW = to_datetime(NOW_MS)


def alert_id(n: int) -> str:
    return f"alt_01a19f93-1150-7000-8000-{n:012d}"


def ticket_id(n: int) -> str:
    return f"tkt_01a19f93-1150-7000-8000-{n:012d}"


def hunt_id(n: int) -> str:
    return f"hnt_01a19f93-1150-7000-8000-{n:012d}"


def insert_alert(conn: psycopg.Connection, n: int, title: str, severity: int = 3) -> None:
    raw_id = f"raw_01a19f93-1150-7000-8000-{n:012d}"
    conn.execute(
        "INSERT INTO raw_records (id, kind, siem_profile, siem_ref, fetched_at, original_text)"
        " VALUES (%s, 'alert', 'fixture', %s, %s, '{}')",
        (raw_id, f"title/{n}", NOW),
    )
    conn.execute(
        "INSERT INTO alerts (id, raw_id, time, severity, title, rule_id, entities, assets,"
        " triage, ocsf, details)"
        " VALUES (%s, %s, %s, %s, %s, 'rule', '[]', '[]', NULL, %s, '{}')",
        (
            alert_id(n),
            raw_id,
            NOW,
            severity,
            title,
            Jsonb({"class_uid": 2004, "time": NOW_MS, "severity_id": severity}),
        ),
    )


def insert_hunt(conn: psycopg.Connection, n: int, hypothesis: str) -> None:
    conn.execute(
        "INSERT INTO hunts (id, hunt_run_id, status, hypothesis, attack_techniques, confidence,"
        " reason, evidence_ids, entities, attempts, verified_at, created_at, updated_at, details)"
        " VALUES (%s, %s, 'confirmed', %s, '{}', 0.8, 'fixture', '{}', '[]', 1, %s, %s, %s, '{}')",
        (
            hunt_id(n),
            f"hrn_01a19f93-1150-7000-8000-{n:012d}",
            hypothesis,
            NOW,
            NOW,
            NOW,
        ),
    )


def insert_legacy_ticket(
    conn: psycopg.Connection,
    n: int,
    origin: str,
    alert_ids: list[str],
    hunt: str | None = None,
) -> None:
    """0109 이전 모양(title 컬럼 없음)의 Ticket 행."""
    conn.execute(
        "INSERT INTO tickets (id, origin, status, alert_ids, hunt_id, entities, verdict,"
        " created_at, updated_at, details)"
        " VALUES (%s, %s, 'new', %s, %s, '[]', NULL, %s, %s, '{}')",
        (ticket_id(n), origin, alert_ids, hunt, NOW, NOW),
    )


@pytest.fixture
def migrated_database(temp_database: HiddenUrl) -> HiddenUrl:
    migrate(temp_database)
    return temp_database


@pytest.fixture
def conn(migrated_database: HiddenUrl) -> Iterator[psycopg.Connection]:
    with psycopg.connect(migrated_database, autocommit=True) as connection:
        yield connection


@pytest.fixture
def legacy_database(temp_database: HiddenUrl, tmp_path: Path) -> HiddenUrl:
    """0109만 빼고 적용한 DB. 마이그레이션 전 데이터를 넣는 데 쓴다."""
    legacy_dir = tmp_path / "legacy_migrations"
    legacy_dir.mkdir()
    for migration in MIGRATIONS_DIR.glob("*.sql"):
        if migration.name != MIGRATION.name:
            shutil.copyfile(migration, legacy_dir / migration.name)
    migrate(temp_database, legacy_dir)
    return temp_database


def titles(conn: psycopg.Connection) -> dict[str, str]:
    return dict(conn.execute("SELECT id, title FROM tickets").fetchall())


def test_migration_adds_not_null_title_to_an_empty_database(conn: psycopg.Connection) -> None:
    column = conn.execute(
        "SELECT is_nullable FROM information_schema.columns"
        " WHERE table_name = 'tickets' AND column_name = 'title'"
    ).fetchone()

    assert column == ("NO",)


def test_migration_backfills_existing_tickets_like_clean_title(
    legacy_database: HiddenUrl,
) -> None:
    """같은 입력(title_cases.json)으로 SQL 백필과 파이썬 clean_title의 결과가 같다."""
    with psycopg.connect(legacy_database, autocommit=True) as legacy:
        for i, (_, text, _) in enumerate(CLEAN, start=1):
            insert_alert(legacy, i, text)
            insert_legacy_ticket(legacy, i, "auto", [alert_id(i)])
            insert_hunt(legacy, i, text)
            insert_legacy_ticket(legacy, 1000 + i, "l3", [], hunt_id(i))

    migrate(legacy_database)

    with psycopg.connect(legacy_database, autocommit=True) as after:
        got = titles(after)
    for i, (case, text, expected) in enumerate(CLEAN, start=1):
        assert got[ticket_id(i)] == expected, case
        assert got[ticket_id(i)] == clean_title(text), case
        assert got[ticket_id(1000 + i)] == expected, case


def test_migration_uses_the_hunt_hypothesis_for_l3_and_the_fallback_without_an_alert(
    legacy_database: HiddenUrl,
) -> None:
    with psycopg.connect(legacy_database, autocommit=True) as legacy:
        insert_hunt(legacy, 1, "  DNS \n beacon  ")
        insert_legacy_ticket(legacy, 1, "l3", [], hunt_id(1))
        insert_legacy_ticket(legacy, 2, "scenario", [alert_id(999)])  # 가리키는 alert가 없다
        insert_alert(legacy, 3, "Port scan")
        insert_legacy_ticket(legacy, 3, "l1", [alert_id(3)])

    migrate(legacy_database)

    with psycopg.connect(legacy_database, autocommit=True) as after:
        assert titles(after) == {
            ticket_id(1): "DNS beacon",
            ticket_id(2): FALLBACK_TITLE,
            ticket_id(3): "Port scan",
        }


def test_title_check_rejects_empty_and_space_only_and_keeps_other_whitespace(
    conn: psycopg.Connection,
) -> None:
    def insert(n: int, title: str | None) -> None:
        conn.execute(
            "INSERT INTO tickets (id, title, origin, status, alert_ids, entities, created_at,"
            " updated_at, details)"
            " VALUES (%s, %s, 'auto', 'new', %s, '[]', %s, %s, '{}')",
            (ticket_id(n), title, [alert_id(n)], NOW, NOW),
        )

    for n, bad in enumerate(["", " ", "\t\n", "\u00a0\u3000", " \t\n\u000b\f\r\u00a0\u3000"], 1):
        with pytest.raises(psycopg.errors.CheckViolation):
            insert(n, bad)
    with pytest.raises(psycopg.errors.NotNullViolation):
        insert(10, None)
    insert(11, " ")  # 목록 밖 공백은 글자로 본다. 계약도 같다

    assert titles(conn) == {ticket_id(11): " "}


def test_title_check_and_clean_title_use_the_same_spaces(conn: psycopg.Connection) -> None:
    """마이그레이션 파일의 CHECK 정규식이 공백으로 보는 글자가 clean_title의 목록과 정확히 같다."""
    literal = re.search(r"title ~ E'([^']*)'", MIGRATION.read_text(encoding="utf-8"))
    assert literal is not None
    regex = literal.group(1).replace("\\\\", "\\")  # E'' 문자열의 이스케이프를 푼다

    rows = conn.execute(
        "SELECT chr(i) FROM generate_series(1, 65535) AS i"
        " WHERE i NOT BETWEEN 55296 AND 57343 AND chr(i) !~ %s",
        (regex,),
    ).fetchall()

    assert {row[0] for row in rows} == set(TITLE_SPACES)


@pytest.mark.parametrize(
    ("alert_title", "expected"),
    [
        ("", FALLBACK_TITLE),
        (" \t\u00a0", FALLBACK_TITLE),
        (" ", " "),
        ("  Unusual   service\nlogin ", "Unusual service login"),
    ],
    ids=["empty", "listed_spaces_only", "unicode_space_only", "normalized"],
)
def test_run_creates_a_ticket_and_does_not_retry_when_the_alert_title_is_unusable(
    conn: psycopg.Connection, alert_title: str, expected: str
) -> None:
    """빈 제목이어도 contract_error 없이 Ticket을 만들고 다시 시도하지 않는다(D-059)."""
    seed = seed_cases(conn, ("auto_alert",))["auto_alert"]
    conn.execute("UPDATE alerts SET title = %s WHERE id = %s", (alert_title, seed["alert"]["id"]))

    first = run(conn, TicketingPolicy("auto", ()), clock=lambda: NOW_MS)
    second = run(conn, TicketingPolicy("auto", ()), clock=lambda: NOW_MS + 1)

    assert (first.candidates, first.created, first.failed) == (1, 1, 0)
    assert (second.candidates, second.created, second.failed) == (0, 0, 0)
    assert list(titles(conn).values()) == [expected]


def test_run_title_equals_the_alert_title_in_scenario_mode_too(conn: psycopg.Connection) -> None:
    seed = seed_cases(conn, ("scenario_match",))["scenario_match"]

    result = run(conn, TicketingPolicy("scenario", ("scenario-rule",)), clock=lambda: NOW_MS)

    assert (result.created, result.failed) == (1, 0)
    assert list(titles(conn).values()) == [clean_title(seed["alert"]["title"])]


def test_fixture_expected_values_are_valid_titles() -> None:
    """샘플의 기대값 자체가 길이 한도 안이다(샘플을 잘못 고쳐 테스트가 통과하는 것을 막는다)."""
    for case in CASES["clean"]:
        assert 1 <= len(expand(case["expected"])) <= 200, case["case"]
