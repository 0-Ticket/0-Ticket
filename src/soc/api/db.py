"""화면용 API의 요청별 DB 연결(#239, #246). DATABASE_URL로 연결하고 요청 뒤 닫는다.

- 읽기 연결은 TimeZone=UTC(#193 기록), statement_timeout, default_transaction_read_only=on을 건다.
- W04 정책 전체 교체만 connect_write()를 써 명시적으로 쓰기 트랜잭션을 연다.
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
    """요청별 읽기 연결. 세션 수준 읽기 전용을 유지한다."""
    with _connect(settings, read_only=True) as conn:
        yield conn


@contextmanager
def connect_write(settings: ApiSettings) -> Iterator[psycopg.Connection]:
    """정책 전체 교체 API용 쓰기 연결. 쓰기 트랜잭션은 호출자가 연다."""
    with _connect(settings, read_only=False) as conn:
        yield conn


@contextmanager
def _connect(settings: ApiSettings, *, read_only: bool) -> Iterator[psycopg.Connection]:
    url = os.environ.get(DATABASE_URL_ENV)
    if not url:
        raise DbUnavailable
    options = [
        "-c TimeZone=UTC",
        f"-c statement_timeout={settings.statement_timeout_ms}",
        f"-c default_transaction_read_only={'on' if read_only else 'off'}",
    ]
    conn = psycopg.connect(
        url,
        connect_timeout=settings.connect_timeout_seconds,
        options=" ".join(options),
        row_factory=dict_row,
    )
    try:
        yield conn
    finally:
        conn.close()
