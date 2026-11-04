"""순번 SQL 마이그레이션 실행기(마이그레이션 방식, D-035).

    uv run python -m soc.db.migrate     # 환경변수 DATABASE_URL의 DB에 적용한다

- migrations/의 NNNN_이름.sql을 번호 순서로, 아직 적용하지 않은 것만 실행한다.
- 번호 대역: 0001~0099 공통, 0100~0199 수집·정규화·L1, 0200~0299 L2, 0300~0399 L3.
  대역은 병렬로 머지되므로 DB마다 대역 사이 적용 순서가 다를 수 있다(0200을 적용한 DB에 늦게
  머지된 0105가 나중에 들어온다). 그래서 마이그레이션은 자기 대역의 테이블만 바꾼다.
  기록된 가장 큰 번호보다 작은 미적용 파일도 멈추지 않고 적용하고, 적용할 때 stderr에 경고
  한 줄을 낸다. 새 DB에서는 번호 순서대로 적용된다.
- 파일 하나를 트랜잭션 하나로 실행하고, schema_migrations 기록도 같은 트랜잭션에 넣는다.
  실패하면 그 파일만 되돌리고 멈춘다.
- 적용한 파일은 고치지 않고 새 번호를 만든다. 파일은 자기보다 작은 번호의 테이블만 참조한다.
- 새 파일을 하나라도 실행하기 전에 이미 적용한 번호를 모두 검사하고, 하나라도 맞지 않으면
  아무것도 실행하지 않고 멈춘다.
  - 기록에 있는 번호의 파일이 없다(번호만 바꾼 파일이 새 번호로 다시 실행되는 것을 막는다).
  - 파일 이름이 기록과 다르다.
  - 파일 내용의 해시가 기록과 다르다(이름은 두고 내용만 고치면 기존 DB와 새 DB의 스키마가
    갈라진다). 해시는 UTF-8로 읽어 \\r\\n을 \\n으로 바꾼 뒤의 SHA-256(hex)이다. Windows의
    core.autocrlf 체크아웃에서도 같은 값이 나오게 하려는 것이다. 강제로 해시를 고치는 옵션은 없다.
- SQL 파일은 BOM 없는 UTF-8로 저장한다. UTF-8이 아니거나(예: CP949) UTF-8 BOM으로 시작하면
  번호와 파일 이름을 담은 MigrationError로 멈춘다. BOM을 떼고 적용하지 않는다.
- 파일은 DB 접속 전에 모두 읽는다. 인코딩 오류와 BOM은 아무것도 적용하지 않는다.
  SQL 오류는 앞 번호가 적용된 채로 멈춘다. 해시 비교와 적용은 이때 읽은 내용을 쓴다
  (비교한 내용을 그대로 적용한다).
- DB 주소(비밀번호 포함)는 출력·로그·예외 메시지에 넣지 않는다.
"""

import hashlib
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path

import psycopg

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

# 숫자는 [0-9]로 쓰고 이름 전체를 fullmatch로 비교한다.
# \d는 유니코드 숫자(٠٠٠١ 등)에도 맞고, $는 마지막 \n 앞에서도 맞기 때문이다.
_NAME = re.compile(r"([0-9]{4})_[a-z0-9_]+\.sql")

_CREATE_HISTORY = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version integer PRIMARY KEY,
    name text NOT NULL,
    checksum text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
)
"""


class MigrationError(Exception):
    """마이그레이션을 찾거나 적용하지 못했다."""


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    path: Path


def find_migrations(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    """번호 순서로 정렬한 마이그레이션 목록. 이름이 규칙에 맞지 않거나 번호가 겹치면 실패한다."""
    found: dict[int, list[Path]] = {}
    for path in sorted(directory.glob("*.sql")):
        match = _NAME.fullmatch(path.name)
        if match is None:
            raise MigrationError(
                f"마이그레이션 파일 이름이 'NNNN_소문자_이름.sql' 규칙에 맞지 않다: {path.name}"
            )
        found.setdefault(int(match.group(1)), []).append(path)

    duplicated = {version: paths for version, paths in found.items() if len(paths) > 1}
    if duplicated:
        listed = "; ".join(" / ".join(p.name for p in paths) for paths in duplicated.values())
        raise MigrationError(f"같은 번호의 마이그레이션이 있다: {listed}")

    return [Migration(version, paths[0].name, paths[0]) for version, paths in sorted(found.items())]


def _read_sql(migration: Migration) -> tuple[str, str]:
    """(실행할 SQL, 내용 해시). 해시를 계산한 텍스트를 그대로 실행한다."""
    try:
        text = migration.path.read_bytes().decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MigrationError(
            f"{migration.version:04d}번({migration.name})을 UTF-8로 읽지 못했다"
            f"({exc.start + 1}번째 바이트). 마이그레이션 파일은 UTF-8로 저장한다"
        ) from None
    if text.startswith("\ufeff"):
        # BOM을 떼고 적용하지 않는다. psql도 클라이언트 인코딩이 UTF8일 때만 떼고 다른 인코딩에서는
        # 문법 오류를 내므로 도구마다 결과가 갈라진다. 같은 SQL의 해시가 BOM 때문에 달라지기도 한다.
        raise MigrationError(
            f"{migration.version:04d}번({migration.name})이 UTF-8 BOM으로 시작한다."
            " 마이그레이션 파일은 BOM 없는 UTF-8로 저장한다"
        )
    sql = text.replace("\r\n", "\n")
    return sql, hashlib.sha256(sql.encode("utf-8")).hexdigest()


def migrate(database_url: str, directory: Path = MIGRATIONS_DIR) -> list[str]:
    """아직 적용하지 않은 마이그레이션을 적용하고, 적용한 파일 이름을 돌려준다."""
    migrations = find_migrations(directory)
    # 번호 → (실행할 SQL, 내용 해시). 해시 비교와 적용 모두 이 내용을 쓰고 파일을 다시 읽지 않는다.
    contents = {m.version: _read_sql(m) for m in migrations}
    try:
        conn = psycopg.connect(database_url, autocommit=True)
    except psycopg.Error:
        # 원래 예외 메시지에는 접속 대상 주소와 계정이 들어 있어 감춘다.
        raise MigrationError(
            "DB에 연결하지 못했다. DATABASE_URL 값과 DB가 실행 중인지 확인한다"
        ) from None

    applied: list[str] = []
    with conn:
        try:
            conn.execute(_CREATE_HISTORY)
            rows = conn.execute("SELECT version, name, checksum FROM schema_migrations")
            done = {version: (name, checksum) for version, name, checksum in rows.fetchall()}
        except psycopg.Error as exc:
            reason = exc.diag.message_primary or type(exc).__name__
            raise MigrationError(f"schema_migrations를 준비하지 못했다: {reason}") from None
        missing = [
            f"{version:04d}번(기록 {done[version][0]})"
            for version in sorted(done.keys() - {m.version for m in migrations})
        ]
        if missing:
            raise MigrationError(
                f"이미 적용한 번호의 파일이 없다(번호를 바꿨는지 확인한다): {'; '.join(missing)}"
            )
        renamed = [
            f"{m.version:04d}번(기록 {done[m.version][0]}, 지금 {m.name})"
            for m in migrations
            if m.version in done and done[m.version][0] != m.name
        ]
        if renamed:
            raise MigrationError(
                f"이미 적용한 번호의 파일 이름이 기록과 다르다: {'; '.join(renamed)}"
            )
        changed = [
            f"{m.version:04d}번({m.name})"
            for m in migrations
            if m.version in done and contents[m.version][1] != done[m.version][1]
        ]
        if changed:
            raise MigrationError(
                "이미 적용한 파일의 내용이 기록과 다르다"
                f"(적용한 파일은 고치지 않고 새 번호를 만든다): {'; '.join(changed)}"
            )
        latest = max(done, default=0)
        for migration in migrations:
            if migration.version in done:
                continue
            if migration.version < latest:
                print(
                    f"경고: {migration.version:04d}번({migration.name})은 이미 적용한"
                    f" 가장 큰 번호 {latest:04d}번보다 작지만 적용한다"
                    "(대역 사이 적용 순서는 DB마다 다를 수 있다)",
                    file=sys.stderr,
                )
            sql, checksum = contents[migration.version]
            try:
                with conn.transaction():
                    # 여러 문장이 든 SQL 파일이다.
                    # 인자 없이 실행해야 여러 문장을 한 번에 보낼 수 있다.
                    conn.execute(sql)
                    conn.execute(
                        "INSERT INTO schema_migrations (version, name, checksum)"
                        " VALUES (%s, %s, %s)",
                        (migration.version, migration.name, checksum),
                    )
            except psycopg.Error as exc:
                reason = exc.diag.message_primary or type(exc).__name__
                raise MigrationError(
                    f"{migration.name} 적용 실패(그 파일은 되돌렸다): {reason}"
                ) from None
            applied.append(migration.name)
    return applied


def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("환경변수 DATABASE_URL이 없다. .env.example을 참고해 설정한다.", file=sys.stderr)
        return 2
    try:
        applied = migrate(database_url)
    except MigrationError as exc:
        print(f"마이그레이션 실패: {exc}", file=sys.stderr)
        return 1
    if applied:
        print(f"마이그레이션 {len(applied)}개를 적용했다: {', '.join(applied)}")
    else:
        print("적용할 마이그레이션이 없다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
