"""도구의 DB 읽기(#211). AGENT_DATABASE_URL(읽기 역할 soc_agent_reader의 멤버 계정)로만 접속한다.

- 도구 호출마다 새로 연결하고, 다 읽으면 닫는다.
- 세션 설정: TimeZone=UTC(#193 기록), statement_timeout, default_transaction_read_only=on.
  읽기 전용 세션은 역할 권한(마이그레이션 0003)이 뚫려도 쓰지 못하게 하는 한 겹 더의 막이다.
- SQL은 매개변수로만 넣는다. 오류는 ToolError 코드로만 알리고, 예외 메시지(주소·SQL)는 버린다.
"""

import os
from collections.abc import Sequence
from typing import Any

import psycopg
from psycopg.rows import dict_row

from soc.tools.registry import CallContext, ToolError

DATABASE_URL_ENV = "AGENT_DATABASE_URL"

Query = tuple[str, Sequence[Any]]


def read_rows(ctx: CallContext, query: str, params: Sequence[Any]) -> list[dict[str, Any]]:
    """문장 하나를 읽는다."""
    return read_many(ctx, [(query, params)])[0]


def read_many(ctx: CallContext, queries: Sequence[Query]) -> list[list[dict[str, Any]]]:
    """한 연결·한 읽기 트랜잭션에서 여러 문장을 읽는다."""
    url = os.environ.get(DATABASE_URL_ENV)
    if not url:
        raise ToolError("unavailable")
    config = ctx.tools_config
    options = (
        "-c TimeZone=UTC"
        f" -c statement_timeout={int(config['statement_timeout_ms'])}"
        " -c default_transaction_read_only=on"
    )
    try:
        conn = psycopg.connect(
            url,
            connect_timeout=int(config["connect_timeout_seconds"]),
            options=options,
            row_factory=dict_row,
        )
    except psycopg.Error:
        raise ToolError("unavailable") from None
    try:
        with conn:
            return [conn.execute(query, params).fetchall() for query, params in queries]
    except psycopg.errors.QueryCanceled:
        raise ToolError("timeout") from None
    except psycopg.OperationalError:
        raise ToolError("unavailable") from None
    except psycopg.Error:
        raise ToolError("failed") from None
