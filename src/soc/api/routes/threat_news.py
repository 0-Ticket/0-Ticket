"""GET /api/threat-news(#239). 수집한 뉴스(#221)를 읽기만 한다.

정렬·기간 기준은 COALESCE(published_at, fetched_at)이다(#223의 가설 생성 입력과 같음).
수집은 fetched_at에 마이크로초까지 넣지만 cursor는 epoch_ms라, 정렬·기간·cursor 비교 모두
밀리초로 자른 값을 쓴다. 자르지 않으면 같은 밀리초 안의 행이 다음 페이지에서 빠진다.
"""

import re
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request
from psycopg import sql

from soc.api import db
from soc.api.auth import require_permission
from soc.api.errors import InvalidQuery
from soc.api.models import NewsPage
from soc.api.routes.hunts import DEFAULT_LIMIT, MAX_LIMIT
from soc.contracts import to_datetime, to_epoch_ms

router = APIRouter()

EPOCH_MS_MAX = 253402214399999
BIGINT_MAX = 9_223_372_036_854_775_807
CURSOR = re.compile(r"^([0-9]{1,15})_([0-9]{1,19})$")

_SORT_AT = "date_trunc('milliseconds', COALESCE(published_at, fetched_at))"
_COLUMNS = (
    "id",
    "source",
    "kind",
    "title",
    "summary",
    "link",
    "published_at",
    "fetched_at",
    "updated_at",
)
_TIMES = ("published_at", "fetched_at", "updated_at")


@router.get(
    "/threat-news", response_model=NewsPage, dependencies=[Depends(require_permission("news.read"))]
)
def list_news(
    request: Request,
    source: Annotated[str | None, Query(min_length=1, max_length=200)] = None,
    since: Annotated[int | None, Query(ge=0, le=EPOCH_MS_MAX)] = None,
    until: Annotated[int | None, Query(ge=0, le=EPOCH_MS_MAX)] = None,
    limit: Annotated[int, Query(ge=1, le=MAX_LIMIT)] = DEFAULT_LIMIT,
    cursor: Annotated[str | None, Query(max_length=40)] = None,
) -> dict[str, Any]:
    if since is not None and until is not None and since > until:
        raise InvalidQuery("since", "until")
    after = _parse_cursor(cursor) if cursor is not None else None

    where: list[sql.Composable] = []
    params: list[Any] = []
    if source is not None:
        where.append(sql.SQL("source = %s"))
        params.append(source)
    if since is not None:
        where.append(sql.SQL(f"{_SORT_AT} >= %s"))
        params.append(to_datetime(since))
    if until is not None:
        where.append(sql.SQL(f"{_SORT_AT} <= %s"))
        params.append(to_datetime(until))
    if after is not None:
        where.append(sql.SQL(f"({_SORT_AT}, id) < (%s, %s)"))
        params += [to_datetime(after[0]), after[1]]
    query = sql.SQL(
        "SELECT {}, {} AS sort_at FROM threat_news {} ORDER BY sort_at DESC, id DESC LIMIT %s"
    ).format(
        sql.SQL(", ").join(map(sql.Identifier, _COLUMNS)),
        sql.SQL(_SORT_AT),
        sql.SQL("WHERE ") + sql.SQL(" AND ").join(where) if where else sql.SQL(""),
    )
    with db.connect(request.app.state.settings) as conn:
        rows = conn.execute(query, [*params, limit + 1]).fetchall()

    page = rows[:limit]
    next_cursor = None
    if len(rows) > limit:
        last = page[-1]
        next_cursor = f"{to_epoch_ms(last['sort_at'])}_{last['id']}"
    items = []
    for row in page:
        item = {key: row[key] for key in _COLUMNS}
        for key in _TIMES:
            if item[key] is not None:
                item[key] = to_epoch_ms(item[key])
        items.append(item)
    return {"items": items, "next_cursor": next_cursor}


def _parse_cursor(cursor: str) -> tuple[int, int]:
    match = CURSOR.match(cursor)
    if match is None:
        raise InvalidQuery("cursor")
    at, news_id = int(match[1]), int(match[2])
    if at > EPOCH_MS_MAX or news_id > BIGINT_MAX:
        raise InvalidQuery("cursor")
    return at, news_id
