"""Alert/Event의 정규화 상태 및 원본 조회."""

from typing import Annotated

from fastapi import APIRouter, Query, Request

from soc.api import db
from soc.api import ui_read as read
from soc.api.ui_models import NormalizeStatus, RawDetail, RawPage

router = APIRouter()
Limit = Annotated[int, Query(ge=1, le=200)]
Cursor = Annotated[str | None, Query(min_length=1, max_length=64)]


def _page(request, kind, status, cursor, limit):
    if cursor:
        read.check_id(cursor, ("raw",), cursor=True)
    with db.connect(request.app.state.settings) as conn:
        return read.raw_page(conn, kind, status, cursor, limit)


def _detail(request, kind, record_id):
    read.check_id(record_id, ("raw", "alt" if kind == "alert" else "evt"))
    with db.connect(request.app.state.settings) as conn:
        return read.raw_detail(conn, kind, record_id)


@router.get("/alerts", response_model=RawPage)
def alerts(
    request: Request,
    status: NormalizeStatus | None = None,
    cursor: Cursor = None,
    limit: Limit = 50,
):
    return _page(request, "alert", status, cursor, limit)


@router.get("/events", response_model=RawPage)
def events(
    request: Request,
    status: NormalizeStatus | None = None,
    cursor: Cursor = None,
    limit: Limit = 50,
):
    return _page(request, "event", status, cursor, limit)


@router.get("/alerts/{record_id}", response_model=RawDetail)
def alert(request: Request, record_id: str):
    return _detail(request, "alert", record_id)


@router.get("/events/{record_id}", response_model=RawDetail)
def event(request: Request, record_id: str):
    return _detail(request, "event", record_id)
