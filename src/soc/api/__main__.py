"""`uv run python -m soc.api`: 화면용 API를 uvicorn으로 띄운다(#239).

종료 코드: 0 정상 종료, 2 설정 오류(DATABASE_URL 없음, DB 연결 실패, 마이그레이션 전 포함).
DB 주소는 출력하지 않는다.

시작할 때 사용자가 0명이면 admin을 만들고 임시 비밀번호를 표준 출력에 1회만 낸다(D-020).
`logging`으로 남기지 않고 DB·파일에도 평문을 두지 않는다.
"""

import os
import sys

import psycopg
import uvicorn

from soc.api import db
from soc.api.app import create_app
from soc.api.config import ConfigError, load_settings
from soc.api.db import DATABASE_URL_ENV
from soc.auth import store


def main() -> int:
    if not os.environ.get(DATABASE_URL_ENV):
        print(f"환경변수 {DATABASE_URL_ENV}가 필요하다")
        return 2
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"설정 오류: {exc}")
        return 2
    try:
        with db.connect_write(settings) as conn:
            temporary = store.ensure_first_admin(conn)
    except psycopg.errors.UndefinedTable:
        print("마이그레이션이 필요하다: uv run python -m soc.db.migrate")
        return 2
    except psycopg.Error:
        print("DB에 연결하지 못했다. DATABASE_URL과 DB 상태를 확인한다")
        return 2
    if temporary:
        print(
            f"최초 관리자 계정을 만들었다. 아이디: {store.FIRST_ADMIN}\n"
            f"임시 비밀번호: {temporary}\n"
            "이 비밀번호는 다시 나오지 않는다. 로그인한 뒤 바로 바꾼다",
            flush=True,
        )
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
