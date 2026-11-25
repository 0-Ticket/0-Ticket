"""마이그레이션 0110: ticketing_policy의 옛 모드 auto를 default로 바꾼다(#297)."""

import shutil
from pathlib import Path

import psycopg
import pytest
from conftest import HiddenUrl

from soc.db.migrate import MIGRATIONS_DIR, migrate

pytestmark = pytest.mark.db

MIGRATION = MIGRATIONS_DIR / "0110_ticketing_policy_default.sql"
INSERT = "INSERT INTO ticketing_policy (id, mode, scenario_rule_ids) VALUES (1, %s, %s)"


@pytest.fixture
def legacy_database(temp_database: HiddenUrl, tmp_path: Path) -> HiddenUrl:
    """0110만 빼고 적용한 DB. 마이그레이션 전 정책 행을 넣는 데 쓴다."""
    legacy_dir = tmp_path / "legacy_migrations"
    legacy_dir.mkdir()
    for migration in MIGRATIONS_DIR.glob("*.sql"):
        if migration.name != MIGRATION.name:
            shutil.copyfile(migration, legacy_dir / migration.name)
    migrate(temp_database, legacy_dir)
    return temp_database


def policy_rows(url: HiddenUrl) -> list[tuple[str, list[str]]]:
    with psycopg.connect(url) as conn:
        return conn.execute("SELECT mode, scenario_rule_ids FROM ticketing_policy").fetchall()


def test_migration_turns_the_old_auto_row_into_default(legacy_database: HiddenUrl) -> None:
    with psycopg.connect(legacy_database, autocommit=True) as legacy:
        legacy.execute(INSERT, ("auto", ["rule-1"]))

    assert migrate(legacy_database) == [MIGRATION.name]

    assert policy_rows(legacy_database) == [("default", ["rule-1"])]


def test_migration_keeps_a_scenario_row(legacy_database: HiddenUrl) -> None:
    with psycopg.connect(legacy_database, autocommit=True) as legacy:
        legacy.execute(INSERT, ("scenario", ["rule-2"]))

    migrate(legacy_database)

    assert policy_rows(legacy_database) == [("scenario", ["rule-2"])]


def test_migration_works_on_an_empty_policy_table(legacy_database: HiddenUrl) -> None:
    migrate(legacy_database)

    assert policy_rows(legacy_database) == []


def test_mode_check_accepts_default_and_scenario_and_rejects_auto(
    legacy_database: HiddenUrl,
) -> None:
    migrate(legacy_database)

    with psycopg.connect(legacy_database, autocommit=True) as conn:
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(INSERT, ("auto", []))
        conn.execute(INSERT, ("default", []))
        conn.execute("DELETE FROM ticketing_policy")
        conn.execute(INSERT, ("scenario", []))


def test_mode_check_name_and_values_are_pinned(legacy_database: HiddenUrl) -> None:
    """이름이 다른 DB를 위한 분기를 두지 않으므로 0110 적용 뒤의 이름과 값을 고정한다."""
    migrate(legacy_database)

    with psycopg.connect(legacy_database) as conn:
        rows = conn.execute(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint"
            " WHERE conrelid = 'ticketing_policy'::regclass AND contype = 'c'"
            " AND conname = 'ticketing_policy_mode_check'"
        ).fetchall()

    assert len(rows) == 1
    definition = rows[0][1]
    assert "'default'" in definition
    assert "'scenario'" in definition
    assert "'auto'" not in definition
