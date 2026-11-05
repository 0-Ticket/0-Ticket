"""화면용 API의 DB 읽기(#239). DATABASE_URL로 요청마다 새로 연결하고, 다 읽으면 닫는다.

- 세션 설정: TimeZone=UTC(#193 기록), statement_timeout, default_transaction_read_only=on.
  DATABASE_URL은 쓰기 권한이 있는 계정이라 읽기 전용 세션을 한 겹 더의 막으로 둔다.
- 에이전트 DB 읽기 역할(AGENT_DATABASE_URL, #211)은 alerts·events만 읽을 수 있어 쓰지 않는다.
- 주소와 psycopg 예외 메시지(호스트가 들어갈 수 있음)는 밖으로 내보내지 않는다.
"""

import os
from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from soc.api.config import ApiSettings

DATABASE_URL_ENV = "DATABASE_URL"


class DbUnavailable(Exception):
    """DATABASE_URL이 없다. 접속·조회 실패는 psycopg.Error 그대로 올린다(둘 다 503)."""


@contextmanager
def connect(settings: ApiSettings) -> Iterator[psycopg.Connection]:
    url = os.environ.get(DATABASE_URL_ENV)
    if not url:
        raise DbUnavailable
    options = (
        "-c TimeZone=UTC"
        f" -c statement_timeout={settings.statement_timeout_ms}"
        " -c default_transaction_read_only=on"
    )
    conn = psycopg.connect(
        url,
        connect_timeout=settings.connect_timeout_seconds,
        options=options,
        row_factory=dict_row,
    )
    try:
        yield conn
    finally:
        conn.close()
