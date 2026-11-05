"""오류 응답(#239). 본문에는 오류 코드와 쿼리 이름만 넣는다.

입력값, 예외 메시지(psycopg 메시지에는 호스트가 들어갈 수 있음), 주소는
본문에도 로그에도 남기지 않는다.
FastAPI 기본 422 본문은 입력값(input)을 넣으므로 처리기를 바꾼다.
"""

import logging
from collections.abc import Awaitable, Callable

import psycopg
from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from soc.api.db import DbUnavailable

logger = logging.getLogger("soc.api")


class InvalidQuery(Exception):
    """형식 검사 뒤에 코드가 찾은 잘못된 쿼리 값(예: since > until, 모양이 틀린 cursor)."""

    def __init__(self, *fields: str) -> None:
        super().__init__()
        self.fields = list(fields)


class NotFound(Exception):
    """없는 ID 또는 모양이 틀린 ID."""


def _error(status: int, code: str, **extra: object) -> JSONResponse:
    return JSONResponse({"error": code, **extra}, status_code=status)


def _invalid(fields: list[str]) -> JSONResponse:
    return _error(422, "invalid_query", fields=fields)


async def _validation(request: Request, exc: RequestValidationError) -> JSONResponse:
    # loc는 ("query", <쿼리 이름>, ...) 모양이다. 쿼리 이름은 라우트가 정한 이름이라 입력값이 아니다
    names: list[str] = []
    for error in exc.errors():
        loc = error.get("loc", ())
        if len(loc) >= 2 and loc[0] == "query" and loc[1] not in names:
            names.append(str(loc[1]))
    return _invalid(sorted(names))


async def _invalid_query(request: Request, exc: InvalidQuery) -> JSONResponse:
    return _invalid(exc.fields)


async def _not_found(request: Request, exc: NotFound) -> JSONResponse:
    return _error(404, "not_found")


async def _http(request: Request, exc: HTTPException) -> JSONResponse:
    if exc.status_code == 404:
        return _error(404, "not_found")
    if exc.status_code == 405:
        return _error(405, "method_not_allowed")
    return _error(exc.status_code, "error")


async def _db(request: Request, exc: Exception) -> JSONResponse:
    logger.error("DB를 쓸 수 없다: %s", type(exc).__name__)
    return _error(503, "db_unavailable")


async def _catch_all(
    request: Request, call_next: Callable[[Request], Awaitable[Response]]
) -> Response:
    # Exception 처리기(add_exception_handler)는 응답을 보낸 뒤 예외를 다시 올려 uvicorn이
    # 메시지가 든 traceback을 남긴다. 미들웨어에서 잡아 다시 올리지 않는다.
    try:
        return await call_next(request)
    except Exception as exc:
        logger.error("처리하지 못한 예외: %s", type(exc).__name__)
        return _error(500, "internal")


def install(app: FastAPI) -> None:
    app.add_exception_handler(RequestValidationError, _validation)
    app.add_exception_handler(InvalidQuery, _invalid_query)
    app.add_exception_handler(NotFound, _not_found)
    app.add_exception_handler(HTTPException, _http)
    app.add_exception_handler(DbUnavailable, _db)
    app.add_exception_handler(psycopg.Error, _db)
    app.middleware("http")(_catch_all)
