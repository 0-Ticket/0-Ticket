"""마이그레이션 실행기에서 DB 없이 확인할 수 있는 것."""

from pathlib import Path

import pytest

from soc.db.migrate import MIGRATIONS_DIR, MigrationError, find_migrations, main, migrate

# 닫힌 포트라 접속은 바로 실패한다. 비밀번호는 가짜 값이다.
UNREACHABLE_URL = "postgresql://someone:not-a-real-password@127.0.0.1:1/somedb"
URL_PARTS = ("not-a-real-password", "someone", "127.0.0.1", "somedb")


def write(directory: Path, name: str, sql: str = "SELECT 1;") -> None:
    (directory / name).write_text(sql, encoding="utf-8")


def test_bundled_migrations_start_with_common_tables() -> None:
    names = [m.name for m in find_migrations(MIGRATIONS_DIR)]

    assert names[0] == "0001_common_tables.sql"


def test_migrations_are_ordered_by_number(tmp_path: Path) -> None:
    for name in ("0100_l1.sql", "0002_b.sql", "0010_c.sql"):
        write(tmp_path, name)
    write(tmp_path, "README.md", "SQL 파일이 아니라서 무시한다")

    found = find_migrations(tmp_path)

    assert [(m.version, m.name) for m in found] == [
        (2, "0002_b.sql"),
        (10, "0010_c.sql"),
        (100, "0100_l1.sql"),
    ]


def test_duplicate_numbers_are_rejected(tmp_path: Path) -> None:
    write(tmp_path, "0001_a.sql")
    write(tmp_path, "0001_b.sql")

    with pytest.raises(MigrationError, match="0001_a.sql.*0001_b.sql"):
        find_migrations(tmp_path)


@pytest.mark.parametrize("name", ["init.sql", "1_short.sql", "0001-dash.sql", "0001_Upper.sql"])
def test_badly_named_sql_files_are_rejected(tmp_path: Path, name: str) -> None:
    write(tmp_path, name)

    with pytest.raises(MigrationError):
        find_migrations(tmp_path)


def test_duplicates_are_found_before_connecting(tmp_path: Path) -> None:
    write(tmp_path, "0001_a.sql")
    write(tmp_path, "0001_b.sql")

    with pytest.raises(MigrationError, match="번호"):
        migrate(UNREACHABLE_URL, tmp_path)


def test_connection_failure_keeps_database_url_out(tmp_path: Path) -> None:
    write(tmp_path, "0001_a.sql")

    with pytest.raises(MigrationError) as excinfo:
        migrate(UNREACHABLE_URL, tmp_path)

    error = excinfo.value
    for part in URL_PARTS:
        assert part not in str(error)
    assert error.__cause__ is None
    assert error.__suppress_context__


def test_main_without_database_url_names_the_variable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    assert main() == 2
    assert "DATABASE_URL" in capsys.readouterr().err


def test_main_failure_keeps_database_url_out(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DATABASE_URL", UNREACHABLE_URL)

    assert main() == 1
    output = capsys.readouterr()
    for part in URL_PARTS:
        assert part not in output.out + output.err
