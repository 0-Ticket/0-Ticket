"""direct SIEM MCP adapter: answers queries from the files the direct connector replays.

For development, tests and demos only (D-037), like the direct connector (box 3):
with ``siem.adapter = "direct"`` the dataset files are the SIEM, so the SIEM MCP
reads those same files. Reading and C2 conversion reuse the connector, so a line
gets the same ``source_record_id`` here as at ingest. To find each record's
entities and time it reuses the box 4 normalizer and its alias tables (C20).

Limits:
- Only the default alias tables and the default ``normalize.max_parse_length``
  are used. An organization's ``normalize.alias_dir`` does not reach this adapter,
  because an adapter factory receives the ``[siem]`` settings only.
- The files are read and normalized once, on the first query, and remembered:
  they do not change while the process runs. A file that cannot be read raises
  ``SiemUnavailableError``, and the next query tries again.

Line content may be attacker-written. It is returned as data and never written
to logs; only counts and file names are.
"""

import copy
import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from soc.config import DirectSiemSettings, SiemSettings, load_config
from soc.contracts import EventRecord, NormalizedAlert
from soc.ingest.connector import to_c2
from soc.ingest.siem.base import HealthStatus
from soc.ingest.siem.direct import DirectSiemConnector
from soc.l1.mcp.siem.base import SiemQuery, SiemUnavailableError
from soc.normalize.alias import load_alias_tables
from soc.normalize.normalizer import Normalizer

logger = logging.getLogger(__name__)

# Entity type -> the normalized fields that can hold it. An ip may be either end.
ENTITY_FIELDS = {"ip": ("src_ip", "dst_ip"), "host": ("host",), "user": ("user",)}
DEFAULT_CHUNK_SIZE = 500
# Normalization stamps failures with a time; nothing here keeps them, so any value works.
_UNUSED_FAILURE_TIME = 0


@dataclass(frozen=True, slots=True)
class _Indexed:
    """One remembered record: its C2 content and what a query matches on."""

    kind: str
    time: int
    entities: Mapping[str, frozenset[str]]
    content: Mapping[str, Any]


class DirectSiemMcp:
    def __init__(
        self,
        settings: DirectSiemSettings,
        normalizer: Normalizer,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ):
        if chunk_size < 1:
            raise ValueError("chunk_size must be at least 1")
        self._connector = DirectSiemConnector(settings)
        self._normalizer = normalizer
        self._chunk_size = chunk_size
        self._records: tuple[_Indexed, ...] | None = None

    def query(self, query: SiemQuery) -> tuple[Mapping[str, Any], ...]:
        if query.entity.type not in ENTITY_FIELDS:
            return ()
        matched = [
            record
            for record in self._indexed()
            if record.kind == query.kind
            and query.start_at <= record.time <= query.end_at
            and query.entity.value in record.entities[query.entity.type]
        ]
        # sorted() is stable: same-time records keep file and line order.
        matched = sorted(matched, key=lambda record: record.time)[: query.limit]
        # Copies, so a caller cannot change what later queries return.
        return tuple(copy.deepcopy(dict(record.content)) for record in matched)

    def health_check(self) -> HealthStatus:
        return self._connector.health_check()

    def _indexed(self) -> tuple[_Indexed, ...]:
        if self._records is None:
            try:
                self._records = self._read_all()
            except OSError:
                # The path is left out: it is settings, but a caller only needs the kind.
                raise SiemUnavailableError("cannot read the direct SIEM files") from None
        return self._records

    def _read_all(self) -> tuple[_Indexed, ...]:
        records: list[_Indexed] = []
        not_normalized = 0
        cursor: str | None = None
        while True:
            batch = self._connector.fetch(cursor, self._chunk_size)
            for item in batch.items:
                indexed = self._index(item)
                if indexed is None:
                    not_normalized += 1
                else:
                    records.append(indexed)
            if batch.next_cursor == cursor:
                break
            cursor = batch.next_cursor
        if not_normalized:
            logger.warning(
                "Skipped %d direct record(s) that do not normalize, so they cannot be matched",
                not_normalized,
            )
        return tuple(records)

    def _index(self, item: Mapping[str, Any]) -> _Indexed | None:
        normalized = self._normalizer.normalize(to_c2(item), _UNUSED_FAILURE_TIME)
        if not isinstance(normalized, NormalizedAlert | EventRecord):
            return None
        entities = {
            entity_type: frozenset(
                value
                for value in (getattr(normalized, field) for field in fields)
                if value is not None
            )
            for entity_type, fields in ENTITY_FIELDS.items()
        }
        return _Indexed(kind=item["kind"], time=normalized.time, entities=entities, content=item)


def create_direct_mcp(settings: SiemSettings, environ: Mapping[str, str]) -> DirectSiemMcp:
    """Factory registered as ``direct``. It needs no address or secret."""
    defaults = load_config(environ={}).normalize
    normalizer = Normalizer(load_alias_tables(None), defaults.max_parse_length)
    return DirectSiemMcp(settings.direct, normalizer, settings.batch_size)
