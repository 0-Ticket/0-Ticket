"""uv run python -m soc.l3.intel: 설정의 출처를 가져와 L3 테이블에 저장한다.

DB 주소는 환경변수 DATABASE_URL이다. 마이그레이션은 하지 않는다
(uv run python -m soc.db.migrate를 먼저 실행한다).
종료 코드: 0 모두 성공, 1 실패한 출처가 있거나 DB 오류, 2 설정 오류.
"""

import os
import sys
from datetime import UTC, datetime

import psycopg

from soc.l3.config import load_config
from soc.l3.intel.collect import (
    ConfigError,
    collect,
    exit_code,
    format_results,
    make_client,
    read_settings,
)


def main() -> int:
    try:
        settings = read_settings(load_config()["l3"])
    except ConfigError as exc:
        print(f"설정 오류: {exc}", file=sys.stderr)
        return 2
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("환경변수 DATABASE_URL이 없다. .env.example을 참고해 설정한다.", file=sys.stderr)
        return 2
    try:
        with (
            psycopg.connect(database_url, autocommit=True) as conn,
            make_client(settings) as client,
        ):
            results = collect(settings, conn, client, now=datetime.now(UTC))
    except psycopg.Error as exc:
        # 원래 예외 메시지에는 접속 대상 주소가 들어 있을 수 있어 종류만 남긴다.
        reason = type(exc).__name__
        print(f"DB 오류({reason}). DATABASE_URL과 마이그레이션을 확인한다", file=sys.stderr)
        return 1
    for line in format_results(results):
        print(line)
    return exit_code(results)


if __name__ == "__main__":
    sys.exit(main())
