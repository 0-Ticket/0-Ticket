"""Paging helpers shared by the list methods of every store (docs/api-contracts.md "공통").

A cursor is an opaque string: the sort key of the last item on a page, as
base64url JSON. Callers pass it back unchanged; a cursor that does not decode
to the expected shape is a ``ValueError``, never a database error.
"""

import base64
import binascii
import json
from collections.abc import Sequence
from typing import Any, Literal, get_args, get_origin

# The list limit of the screen API: default 50, at most 200.
DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 200


class InvalidCursorError(ValueError):
    """The cursor was not made by this store's list method."""


def check_page_limit(limit: int) -> None:
    if not 1 <= limit <= MAX_PAGE_LIMIT:
        raise ValueError(f"limit must be between 1 and {MAX_PAGE_LIMIT}")


def encode_cursor(key: Sequence[int | str]) -> str:
    text = json.dumps(list(key), separators=(",", ":"), ensure_ascii=False)
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


def decode_cursor(cursor: str, types: Sequence[type]) -> tuple[Any, ...]:
    """Decode ``cursor`` into a tuple whose items have exactly ``types``."""
    try:
        value = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8"))
    except (UnicodeError, binascii.Error, ValueError):
        raise InvalidCursorError("cursor is not valid") from None
    if not isinstance(value, list) or len(value) != len(types):
        raise InvalidCursorError("cursor is not valid")
    for item, expected in zip(value, types, strict=True):
        # bool is an int in Python; a cursor never holds one.
        if isinstance(item, bool) or not isinstance(item, expected):
            raise InvalidCursorError("cursor is not valid")
    return tuple(value)


def literal_values(model: Any, field: str) -> frozenset[str]:
    """The enum values a generated contract model allows for ``field`` (None left out)."""
    annotation = model.model_fields[field].annotation
    # Literal[...] or Literal[...] | None
    parts = (annotation,) if get_origin(annotation) is Literal else get_args(annotation)
    values: set[str] = set()
    for part in parts:
        if get_origin(part) is Literal:
            values.update(v for v in get_args(part) if isinstance(v, str))
    return frozenset(values)


def check_filter(name: str, value: str | None, allowed: frozenset[str]) -> None:
    if value is not None and value not in allowed:
        raise ValueError(f"{name} must be one of {', '.join(sorted(allowed))}")
