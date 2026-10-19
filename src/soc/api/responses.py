"""Response shapes of docs/api-contracts.md "공통": list pages and errors.

Every response body is a contract object, a page of them, or an error. The API
adds no fields of its own.
"""

from collections.abc import Callable, Mapping
from typing import Any

from fastapi.responses import JSONResponse

# docs/api-contracts.md: one HTTP status per error code.
STATUS = {"invalid_input": 400, "not_found": 404, "conflict": 409, "internal": 500}


def as_json(value: Any) -> Any:
    """A contract object as JSON: generated models are dumped, plain dicts pass through."""
    dump = getattr(value, "model_dump", None)
    return dump(mode="json") if callable(dump) else value


def page(items: Any, next_cursor: str | None) -> dict[str, Any]:
    return {"items": [as_json(item) for item in items], "next_cursor": next_cursor}


def error(code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=STATUS[code])


def not_found(what: str) -> JSONResponse:
    return error("not_found", f"{what} not found")


def drain(list_page: Callable[..., Any], **filters: Any) -> list[Any]:
    """Every item of a filtered list, following ``next_cursor`` to the last page.

    A detail response holds one subject's whole history, which can be longer
    than a page.
    """
    items: list[Any] = []
    cursor = None
    while True:
        result = list_page(cursor=cursor, **filters)
        items += [as_json(item) for item in result.items]
        if result.next_cursor is None or result.next_cursor == cursor:
            # Equal cursors would mean the store is not advancing; stop instead of looping.
            return items
        cursor = result.next_cursor


def findings_of(requests: list[Mapping[str, Any]]) -> list[Any]:
    """The C14 of every completed specialist request (docs/api-contracts.md "티켓 상세")."""
    return [
        request["result"]["finding"]
        for request in requests
        if request["request_type"] == "specialist_agent" and request["status"] == "completed"
    ]
