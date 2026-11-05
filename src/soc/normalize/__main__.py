"""정규화를 한 번 실행하고 끝낸다. 주기 실행은 cron이 한다.

    uv run python -m soc.normalize

종료 코드: 0 실패 없음, 1 실패한 건이 있거나 DB에 접속·조회하지 못함, 2 설정·환경변수 오류.
"""

import os
import sys
import tomllib
import uuid

import psycopg

from soc.api.db import DATABASE_URL_ENV
from soc.normalize.config import ConfigError, load_settings
from soc.normalize.run import RunResult, exit_code, run


def main() -> int:
    """설정을 읽고 연결을 열어 정규화를 한 번 실행한다."""
    try:
        settings = load_settings()
    except (ConfigError, OSError, tomllib.TOMLDecodeError) as error:
        print(f"설정 오류: {error}", file=sys.stderr)
        return 2
    url = os.environ.get(DATABASE_URL_ENV)
    if not url:
        print(f"환경변수 {DATABASE_URL_ENV}가 필요하다", file=sys.stderr)
        return 2
    try:
        with psycopg.connect(
            url, autocommit=True, connect_timeout=settings.connect_timeout_seconds
        ) as conn:
            result = run(settings, conn, uuid.uuid4().hex)
    except psycopg.Error:
        print("DB에 접속하지 못했거나 조회·저장에 실패했다", file=sys.stderr)
        return 1
    print(_format(result))
    return exit_code(result)


def _format(result: RunResult) -> str:
    """실행 결과를 한 줄로 만든다. 실패 코드별 건수를 뒤에 붙인다.

    Args:
        result: run의 결과.
    """
    line = (
        f"claimed={result.claimed} succeeded={result.succeeded}"
        f" failed={result.failed} lease_lost={result.lease_lost}"
    )
    failures = " ".join(f"{code}={count}" for code, count in sorted(result.failures.items()))
    return f"{line} {failures}".rstrip()


if __name__ == "__main__":
    sys.exit(main())
