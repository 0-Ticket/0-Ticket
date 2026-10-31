"""direct adapter: replays dataset files as C1 -> C2 without a SIEM (box 3, D-004, D-037).

For development, tests and demos only; production always connects to a SIEM.
Each non-blank line of a configured file becomes one C1 RawRecord and one C2
content (no ``source_record_id``: the core entry assigns it). Line content may
be attacker-written, so it is kept as data and never written to logs or error
messages; only file names and line numbers are.
"""

import hashlib
import json
import logging
import os
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from soc.config import DirectFileSettings, DirectSiemSettings, Settings, SiemSettings
from soc.contracts import RawRecord, validate_contract
from soc.normalize.alias import (
    CompiledAliasTable,
    MappingAwareFactory,
    MappingSelection,
    load_alias_tables,
    mapping_profile_for,
)

from .base import FetchBatch, HealthStatus, InvalidCursorError

logger = logging.getLogger(__name__)


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


@dataclass(frozen=True)
class Replay:
    """One fetch with the C1 records behind its C2 contents, in the same order."""

    records: tuple[RawRecord, ...]
    batch: FetchBatch


class _SkipLine(Exception):
    """The line cannot become C2. The message names the reason, never the content."""


def _reject_constant(name: str) -> Any:
    raise _SkipLine(f"JSON constant {name} is not allowed")


def _strip_line_end(raw: bytes) -> bytes:
    if raw.endswith(b"\n"):
        raw = raw[:-1]
    if raw.endswith(b"\r"):
        raw = raw[:-1]
    return raw


class DirectSiemConnector:
    """Cursor: ``<file index>:<byte offset>:<lines read>``. A resume seeks, never rereads."""

    def __init__(
        self,
        settings: DirectSiemSettings,
        clock: Callable[[], int] = _now_ms,
        *,
        alias_tables: Mapping[str, CompiledAliasTable] | None = None,
    ):
        self._files = settings.files
        self._clock = clock
        tables = load_alias_tables(None) if alias_tables is None else alias_tables
        self._profiles = {
            (entry.tool, entry.log_type, entry.kind): mapping_profile_for(
                tables, entry.tool, entry.log_type, entry.kind
            )
            for entry in self._files
        }

    def fetch(self, cursor: str | None, limit: int) -> FetchBatch:
        return self.replay(cursor, limit).batch

    def replay(self, cursor: str | None, limit: int) -> Replay:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        index, offset, line_number = self._parse_cursor(cursor)
        records: list[RawRecord] = []
        items: list[dict[str, Any]] = []
        skipped = 0
        while index < len(self._files) and len(items) < limit:
            entry = self._files[index]
            reached_end = False
            with open(entry.path, "rb") as handle:
                handle.seek(offset)
                while len(items) < limit:
                    raw = handle.readline()
                    if not raw:
                        reached_end = True
                        break
                    offset += len(raw)
                    line_number += 1
                    line = _strip_line_end(raw)
                    if not line.strip():
                        continue
                    try:
                        record, item = self._convert(entry, line, line_number)
                    except _SkipLine as reason:
                        skipped += 1
                        logger.warning(
                            "Skipped %s line %d: %s", Path(entry.path).name, line_number, reason
                        )
                        continue
                    records.append(record)
                    items.append(item)
            if reached_end:
                index, offset, line_number = index + 1, 0, 0
        moved = items or skipped
        next_cursor = f"{index}:{offset}:{line_number}" if moved else cursor
        batch = FetchBatch(items=tuple(items), next_cursor=next_cursor, skipped=skipped)
        return Replay(records=tuple(records), batch=batch)

    def health_check(self) -> HealthStatus:
        if not self._files:
            return HealthStatus(ok=False, detail="no files configured in siem.direct.files")
        unreadable = [
            Path(entry.path).name
            for entry in self._files
            if not (Path(entry.path).is_file() and os.access(entry.path, os.R_OK))
        ]
        if unreadable:
            return HealthStatus(ok=False, detail=f"cannot read: {', '.join(unreadable)}")
        return HealthStatus(ok=True, detail=f"{len(self._files)} files readable")

    def _parse_cursor(self, cursor: str | None) -> tuple[int, int, int]:
        if cursor is None:
            return 0, 0, 0
        parts = cursor.split(":")
        if len(parts) != 3 or not all(part.isdigit() for part in parts):
            raise InvalidCursorError("direct cursor must be <file index>:<offset>:<lines read>")
        index, offset, line_number = (int(part) for part in parts)
        if index > len(self._files):
            raise InvalidCursorError("direct cursor points past the configured files")
        return index, offset, line_number

    def _convert(
        self, entry: DirectFileSettings, line: bytes, line_number: int
    ) -> tuple[RawRecord, dict[str, Any]]:
        try:
            payload = line.decode("utf-8")
        except UnicodeDecodeError:
            raise _SkipLine("not valid UTF-8") from None
        name = Path(entry.path).name
        raw_id = f"raw_{name}_{line_number}"
        record = validate_contract(
            "RawRecord",
            {
                "raw_id": raw_id,
                "source_type": entry.source_type,
                "received_at": self._clock(),
                "payload": payload,
                "sha256": hashlib.sha256(line).hexdigest(),
            },
        )
        item = {
            "kind": entry.kind,
            "mapping_profile": self._profiles[(entry.tool, entry.log_type, entry.kind)],
            "raw_ids": [raw_id],
            "fields": self._fields(entry.format, payload, name),
        }
        return record, item

    @staticmethod
    def _fields(line_format: str, payload: str, file_name: str) -> dict[str, Any]:
        if line_format == "text":
            # Not parsed here: box 4 alias tables map fields, the adapter only replays.
            return {"message": payload, "source_file": file_name}
        try:
            fields = json.loads(payload, parse_constant=_reject_constant)
        except json.JSONDecodeError:
            raise _SkipLine("not valid JSON") from None
        if not isinstance(fields, dict):
            raise _SkipLine("not a JSON object")
        try:
            # A \ud800-style escape decodes to a lone surrogate the core cannot hash.
            json.dumps(fields, ensure_ascii=False).encode("utf-8")
        except UnicodeEncodeError:
            raise _SkipLine("holds a string that is not valid UTF-8") from None
        return fields


def create_direct(
    settings: SiemSettings,
    environ: Mapping[str, str],
    *,
    alias_tables: Mapping[str, CompiledAliasTable] | None = None,
) -> DirectSiemConnector:
    """Factory registered as ``direct``. It needs no address or secret."""
    return DirectSiemConnector(settings.direct, alias_tables=alias_tables)


def _mapping_selections(settings: SiemSettings) -> tuple[MappingSelection, ...]:
    return tuple(
        MappingSelection(file.kind, file.tool, file.log_type) for file in settings.direct.files
    )


def _configured_factory(
    settings: Settings,
    environ: Mapping[str, str],
    tables: Mapping[str, CompiledAliasTable],
) -> DirectSiemConnector:
    return create_direct(settings.siem, environ, alias_tables=tables)


MAPPING_AWARE_DIRECT_FACTORY = MappingAwareFactory(_mapping_selections, _configured_factory)
