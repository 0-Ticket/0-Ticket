"""CSV asset and account tables (box 7) -> C4 rows the Lookup store accepts.

Format (UTF-8, a BOM is ignored, cells are trimmed):

- assets: ``match, hostname, criticality, shared`` required; ``owner, zone,
  valid_from, valid_to`` optional.
- users: ``user, privileged`` required; ``dept, valid_from, valid_to`` optional.
  The account period is kept beside UserInfo, which has no validity fields.
- A column named ``<org>.<field>`` goes to ``extensions`` as text; an empty cell
  leaves it out. Any other column name is rejected.
- Booleans are ``true`` / ``false`` (any case). Times are epoch ms integers or
  ISO 8601 with a time zone. An empty optional cell is null.

Errors give the line and the column, never the cell value.
"""

import csv
import io
import re
from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from soc.contracts import AssetInfo
from soc.store.lookups.base import InvalidLookupRows, UserRow
from soc.store.lookups.checks import check_assets, check_users

EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
ONE_MS = timedelta(milliseconds=1)
INTEGER = re.compile(r"-?[0-9]+")
EXTENSION_COLUMN = re.compile(r"[^.]+\..+")


class LookupTableError(ValueError):
    """A CSV table that cannot be loaded. The message names the line and column only."""


class _CellError(ValueError):
    pass


def _text(cell: str) -> str:
    return cell


def _integer(cell: str) -> int:
    if not INTEGER.fullmatch(cell):
        raise _CellError("not an integer")
    return int(cell)


def _boolean(cell: str) -> bool:
    lowered = cell.lower()
    if lowered not in ("true", "false"):
        raise _CellError("not true or false")
    return lowered == "true"


def _time(cell: str) -> int:
    if INTEGER.fullmatch(cell):
        return int(cell)
    try:
        moment = datetime.fromisoformat(cell)
    except ValueError:
        raise _CellError("not epoch ms or ISO 8601") from None
    if moment.tzinfo is None:
        raise _CellError("ISO 8601 time without a time zone")
    return (moment - EPOCH) // ONE_MS


Parser = Callable[[str], Any]

ASSET_COLUMNS: Mapping[str, Parser] = {
    "match": _text,
    "hostname": _text,
    "criticality": _integer,
    "owner": _text,
    "zone": _text,
    "shared": _boolean,
    "valid_from": _time,
    "valid_to": _time,
}
ASSET_REQUIRED = ("match", "hostname", "criticality", "shared")

USER_COLUMNS: Mapping[str, Parser] = {
    "user": _text,
    "dept": _text,
    "privileged": _boolean,
    "valid_from": _time,
    "valid_to": _time,
}
USER_REQUIRED = ("user", "privileged")


def parse_assets_csv(text: str) -> list[AssetInfo]:
    """An asset table as C4 AssetInfo rows, checked as the store would check them."""
    lines, rows = _read(text, ASSET_COLUMNS, ASSET_REQUIRED)
    try:
        return check_assets(rows)
    except InvalidLookupRows as error:
        raise _row_error(lines, error) from None


def parse_users_csv(text: str) -> list[UserRow]:
    """An account table as C4 UserInfo rows with their periods, checked as the store would."""
    lines, rows = _read(text, USER_COLUMNS, USER_REQUIRED)
    try:
        return check_users(rows)
    except InvalidLookupRows as error:
        raise _row_error(lines, error) from None


def _read(
    text: str, columns: Mapping[str, Parser], required: tuple[str, ...]
) -> tuple[list[int], list[dict[str, Any]]]:
    reader = csv.reader(io.StringIO(text.removeprefix("﻿")))
    header_cells = next(reader, None)
    if header_cells is None:
        raise LookupTableError("line 1: no header")
    header = [cell.strip() for cell in header_cells]
    _check_header(header, columns, required)

    lines: list[int] = []
    rows: list[dict[str, Any]] = []
    for cells in reader:
        if not any(cell.strip() for cell in cells):
            continue
        line = reader.line_num
        if len(cells) != len(header):
            raise LookupTableError(f"line {line}: has {len(cells)} cells, header has {len(header)}")
        row: dict[str, Any] = dict.fromkeys(columns)
        extensions: dict[str, str] = {}
        for column, raw in zip(header, cells, strict=True):
            cell = raw.strip()
            if column in columns:
                row[column] = _convert(columns[column], cell, line, column)
            elif cell:
                extensions[column] = cell
        row["extensions"] = extensions
        lines.append(line)
        rows.append(row)
    return lines, rows


def _check_header(header: list[str], columns: Mapping[str, Parser], required: tuple[str, ...]):
    seen: set[str] = set()
    for column in header:
        if column in seen:
            raise LookupTableError(f"line 1: column {column}: repeated")
        seen.add(column)
        if column not in columns and not EXTENSION_COLUMN.fullmatch(column):
            raise LookupTableError(
                f"line 1: column {column}: unknown; extensions are named <org>.<field>"
            )
    for column in required:
        if column not in seen:
            raise LookupTableError(f"line 1: column {column}: missing")


def _convert(parser: Parser, cell: str, line: int, column: str) -> Any:
    if cell == "":
        return None
    try:
        return parser(cell)
    except _CellError as error:
        raise LookupTableError(f"line {line}: column {column}: {error}") from None


def _row_error(lines: list[int], error: InvalidLookupRows) -> LookupTableError:
    return LookupTableError(f"line {lines[error.index]}: column {error.field}: {error.reason}")
