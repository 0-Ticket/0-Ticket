"""elastic adapter: alerts and events from Elasticsearch + Kibana Security (box 3, D-037, #99).

Kibana detection rules write alerts to ``[siem.elastic] alert_index``; access
logs live in ``event_index``. Each ``_search`` hit becomes one C2 content (no
``source_record_id``: the core entry assigns it):

- ``scenario``: ``elastic_security_alert`` or ``elastic_access_event``, the
  default alias tables of box 4. An organization replaces a table by its name.
- ``raw_ids``: ``raw_es_<index>_<_id>``, from the concrete index the hit names.
  The SIEM keeps the original document (D-037), so no C1 is made here; the
  direct adapter's C1 is not stored either.
- ``fields``: ``_source`` with dotted keys (``"kibana.alert.severity"``) expanded
  into nested objects, which Elasticsearch treats as the same document. A key
  given both ways cannot be expanded and the hit is skipped. Alert fields Kibana
  changes later (``MUTABLE_ALERT_FIELDS``) are left out, so the same alert read
  again gets the same ``source_record_id``.

Cursor: for each index, the last ``@timestamp`` read (epoch ms) and the ``_id``s
already read at that time. The next read asks for ``@timestamp >= that time``
minus those ``_id``s, so many documents in one second are neither lost nor
repeated, and it never sorts on ``_id`` (refused by default since ES 8). A
document indexed later with an older ``@timestamp`` than the cursor is missed.
Alerts are read first; what the batch has left goes to events.

Only reads: ``POST /<index>/_search`` with a query, and ``GET /<index>/_search?size=0``
as the health check. Hit content may be attacker-written: it is never logged or
put in an error message, and neither is the API key.
"""

import base64
import binascii
import json
import logging
import ssl
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen

from soc.config import (
    ConfigError,
    ElasticSiemSettings,
    SiemSettings,
    read_secret,
    validate_http_base_url,
)

from .base import FetchBatch, HealthStatus, InvalidCursorError

logger = logging.getLogger(__name__)

ALERT_SCENARIO = "elastic_security_alert"
EVENT_SCENARIO = "elastic_access_event"
TIME_FIELD = "@timestamp"
RAW_ID_PREFIX = "raw_es_"
CURSOR_VERSION = 1

# Alert fields Kibana rewrites after the alert is written (status, triage, timestamps).
# Kept out of C2 so a re-read alert keeps its source_record_id. One place to edit:
# check it against the lab's alert documents (#99).
MUTABLE_ALERT_FIELDS: tuple[str, ...] = (
    "kibana.alert.workflow_status",
    "kibana.alert.workflow_tags",
    "kibana.alert.workflow_user",
    "kibana.alert.workflow_status_updated_at",
    "kibana.alert.workflow_assignee_ids",
    "kibana.alert.status",
    "kibana.alert.last_detected",
    "kibana.alert.updated_at",
    "kibana.alert.updated_by.user.id",
    "kibana.alert.updated_by.user.name",
)


class ElasticError(RuntimeError):
    """A request failed. The message names the failure and HTTP status, never content."""

    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


class ElasticUnreachableError(ElasticError):
    """No answer at all: no connection or no answer in time. ``status`` is None."""


class UnusableHitError(ValueError):
    """A hit cannot become C2. The message names the reason, never the content."""


class ElasticClient:
    """The two read requests the elastic adapters send. Holds the API key; never shows it."""

    def __init__(self, base_url: str, api_key: str, verify_tls: bool, timeout_seconds: int):
        self._base_url = base_url.rstrip("/")
        self._authorization = f"ApiKey {api_key}"
        self._timeout = timeout_seconds
        self._context: ssl.SSLContext | None = None
        if not verify_tls:
            logger.warning("TLS certificate checks are off for the SIEM (siem.verify_tls = false)")
            self._context = ssl.create_default_context()
            self._context.check_hostname = False
            self._context.verify_mode = ssl.CERT_NONE

    def __repr__(self) -> str:
        return f"ElasticClient({self._base_url!r})"

    def search(self, index: str, body: Mapping[str, Any]) -> dict[str, Any]:
        """``POST /<index>/_search`` with ``body``; the answer as a dict."""
        return self._send("POST", index, "", json.dumps(body).encode("utf-8"))

    def probe(self, index: str) -> None:
        """``GET /<index>/_search?size=0``: the key can read the index, nothing returned."""
        self._send("GET", index, "?size=0", None)

    def _send(self, method: str, index: str, query: str, data: bytes | None) -> dict[str, Any]:
        url = f"{self._base_url}/{quote(index, safe='*')}/_search{query}"
        headers = {"Authorization": self._authorization, "Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        request = Request(url, data=data, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self._timeout, context=self._context) as response:
                raw = response.read()
        except HTTPError as error:
            status = error.code
            error.close()
            # The answer body may repeat the query, which holds log values: leave it out.
            raise ElasticError(f"Elasticsearch answered HTTP {status}", status) from None
        except TimeoutError:
            raise ElasticUnreachableError("Elasticsearch did not answer in time") from None
        except URLError as error:
            if isinstance(error.reason, TimeoutError):
                raise ElasticUnreachableError("Elasticsearch did not answer in time") from None
            raise ElasticUnreachableError("cannot reach Elasticsearch") from None
        except OSError:
            raise ElasticUnreachableError("cannot reach Elasticsearch") from None
        try:
            answer = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            raise ElasticError("Elasticsearch answer is not JSON") from None
        if not isinstance(answer, dict):
            raise ElasticError("Elasticsearch answer is not a JSON object")
        return answer


def expand_dotted_keys(value: Any) -> Any:
    """``{"a.b": 1}`` -> ``{"a": {"b": 1}}`` at every level, lists included.

    Raises UnusableHitError when one field is given twice (``"a.b"`` and ``{"a": {"b"}}``)
    or a key has an empty part (``"a..b"``).
    """
    if isinstance(value, list):
        return [expand_dotted_keys(item) for item in value]
    if not isinstance(value, dict):
        return value
    expanded: dict[str, Any] = {}
    for key, item in value.items():
        parts = key.split(".")
        if "" in parts:
            raise UnusableHitError("has a field name with an empty part")
        _put(expanded, parts, expand_dotted_keys(item))
    return expanded


def _put(target: dict[str, Any], parts: Sequence[str], value: Any) -> None:
    for part in parts[:-1]:
        child = target.setdefault(part, {})
        if not isinstance(child, dict):
            raise UnusableHitError("gives one field twice")
        target = child
    leaf = parts[-1]
    if leaf not in target:
        target[leaf] = value
    elif isinstance(target[leaf], dict) and isinstance(value, dict):
        for key, item in value.items():
            _put(target[leaf], [key], item)
    else:
        raise UnusableHitError("gives one field twice")


def _drop(fields: dict[str, Any], path: str) -> None:
    """Remove ``path`` and any object left empty along it, whether or not ES removed it first."""
    chain: list[tuple[dict[str, Any], str]] = []
    node: Any = fields
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            break
        chain.append((node, part))
        node = node[part]
    else:
        parent, key = chain.pop()
        del parent[key]
    for parent, key in reversed(chain):
        if parent[key] == {}:
            del parent[key]


def hit_to_c2(hit: Mapping[str, Any], kind: str, scenario: str) -> dict[str, Any]:
    """One ``_search`` hit -> C2 content without ``source_record_id``. Raises UnusableHitError."""
    index, doc_id, source = hit.get("_index"), hit.get("_id"), hit.get("_source")
    if not isinstance(index, str) or not index or not isinstance(doc_id, str) or not doc_id:
        raise UnusableHitError("has no index or id")
    if not isinstance(source, dict):
        raise UnusableHitError("_source is not an object")
    fields = expand_dotted_keys(source)
    if kind == "alert":
        for path in MUTABLE_ALERT_FIELDS:
            _drop(fields, path)
    try:
        # The core hashes this as plain JSON; NaN or a lone surrogate would not survive.
        json.dumps(fields, ensure_ascii=False, allow_nan=False).encode("utf-8")
    except (ValueError, UnicodeEncodeError):
        raise UnusableHitError("holds a value that is not plain JSON") from None
    return {
        "kind": kind,
        "scenario": scenario,
        "raw_ids": [f"{RAW_ID_PREFIX}{index}_{doc_id}"],
        "fields": fields,
    }


@dataclass(frozen=True)
class _Position:
    """Last ``@timestamp`` read in one index and the ``_id``s read at exactly that time."""

    time: int
    ids: tuple[str, ...]


@dataclass(frozen=True)
class _Source:
    kind: str
    index: str
    scenario: str


@dataclass(frozen=True)
class _Read:
    items: list[dict[str, Any]]
    reasons: list[str]
    position: _Position | None


def _encode_cursor(positions: Mapping[str, _Position | None]) -> str:
    data: dict[str, Any] = {"v": CURSOR_VERSION}
    for kind, position in positions.items():
        data[kind] = None if position is None else {"t": position.time, "ids": list(position.ids)}
    text = json.dumps(data, sort_keys=True, separators=(",", ":"))
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def _decode_cursor(cursor: str, kinds: Sequence[str]) -> dict[str, _Position | None]:
    invalid = InvalidCursorError("elastic cursor was not made by this connector")
    try:
        standard = cursor.replace("-", "+").replace("_", "/")
        raw = base64.b64decode(standard + "=" * (-len(standard) % 4), validate=True)
        data = json.loads(raw.decode("utf-8"))
    except (binascii.Error, ValueError, UnicodeError):
        raise invalid from None
    if not isinstance(data, dict) or set(data) != {"v", *kinds} or data["v"] != CURSOR_VERSION:
        raise invalid
    positions: dict[str, _Position | None] = {}
    for kind in kinds:
        entry = data[kind]
        if entry is None:
            positions[kind] = None
            continue
        if not isinstance(entry, dict) or set(entry) != {"t", "ids"}:
            raise invalid
        time, ids = entry["t"], entry["ids"]
        if type(time) is not int or not isinstance(ids, list):
            raise invalid
        if not ids or not all(isinstance(doc_id, str) and doc_id for doc_id in ids):
            raise invalid
        positions[kind] = _Position(time, tuple(ids))
    return positions


def _advance(position: _Position | None, time: int, doc_id: str) -> _Position:
    if position is not None and time == position.time:
        return _Position(time, (*position.ids, doc_id))
    if position is not None and time < position.time:
        raise ElasticError("Elasticsearch answer is not in time order")
    return _Position(time, (doc_id,))


def _sort_time(hit: Mapping[str, Any]) -> int:
    sort = hit.get("sort")
    if not isinstance(sort, list) or not sort or type(sort[0]) is not int:
        raise ElasticError("Elasticsearch answer holds a hit without a time sort value")
    return sort[0]


def search_hits(answer: Mapping[str, Any]) -> list[Any]:
    hits = answer.get("hits")
    found = hits.get("hits") if isinstance(hits, dict) else None
    if not isinstance(found, list):
        raise ElasticError("Elasticsearch answer has no hits list")
    return found


class ElasticSiemConnector:
    def __init__(self, client: ElasticClient, settings: ElasticSiemSettings):
        self._client = client
        self._sources = (
            _Source("alert", settings.alert_index, ALERT_SCENARIO),
            _Source("event", settings.event_index, EVENT_SCENARIO),
        )

    def fetch(self, cursor: str | None, limit: int) -> FetchBatch:
        if limit < 1:
            raise ValueError("limit must be at least 1")
        kinds = [source.kind for source in self._sources]
        if cursor is None:
            positions: dict[str, _Position | None] = dict.fromkeys(kinds)
        else:
            positions = _decode_cursor(cursor, kinds)
        items: list[dict[str, Any]] = []
        skipped = 0
        moved = False
        for source in self._sources:
            room = limit - len(items) - skipped
            if room <= 0:
                break
            read = self._read(source, positions[source.kind], room)
            items.extend(read.items)
            skipped += len(read.reasons)
            if read.reasons:
                logger.warning(
                    "Skipped %d Elasticsearch hit(s) from %s that cannot become C2: %s",
                    len(read.reasons),
                    source.index,
                    ", ".join(sorted(set(read.reasons))),
                )
            if read.position != positions[source.kind]:
                positions[source.kind] = read.position
                moved = True
        next_cursor = _encode_cursor(positions) if moved else cursor
        return FetchBatch(items=tuple(items), next_cursor=next_cursor, skipped=skipped)

    def health_check(self) -> HealthStatus:
        for label, source in zip(("alert index", "event index"), self._sources, strict=True):
            try:
                self._client.probe(source.index)
            except ElasticError as error:
                detail = f"{label} {source.index}: {error}"
                if error.status in {401, 403}:
                    detail += " (check the API key and its read privilege on this index)"
                return HealthStatus(ok=False, detail=detail)
        return HealthStatus(ok=True, detail="alert index and event index are readable")

    def _read(self, source: _Source, position: _Position | None, size: int) -> _Read:
        answer = self._client.search(source.index, _search_body(source.kind, position, size))
        items: list[dict[str, Any]] = []
        reasons: list[str] = []
        for hit in search_hits(answer):
            if not isinstance(hit, dict) or not isinstance(hit.get("_id"), str) or not hit["_id"]:
                raise ElasticError("Elasticsearch answer holds a hit without an id")
            position = _advance(position, _sort_time(hit), hit["_id"])
            try:
                items.append(hit_to_c2(hit, source.kind, source.scenario))
            except UnusableHitError as reason:
                reasons.append(str(reason))
        return _Read(items=items, reasons=reasons, position=position)


def _search_body(kind: str, position: _Position | None, size: int) -> dict[str, Any]:
    """The structured query for the hits after ``position``, oldest first."""
    filters: list[dict[str, Any]] = [{"exists": {"field": TIME_FIELD}}]
    query: dict[str, Any] = {"filter": filters}
    if position is not None:
        filters.append({"range": {TIME_FIELD: {"gte": position.time, "format": "epoch_millis"}}})
        query["must_not"] = [{"ids": {"values": list(position.ids)}}]
    body: dict[str, Any] = {
        "size": size,
        # numeric_type "date" gives epoch ms sort values for date and date_nanos fields alike.
        "sort": [{TIME_FIELD: {"order": "asc", "numeric_type": "date"}}],
        "query": {"bool": query},
        "track_total_hits": False,
    }
    if kind == "alert":
        body["_source"] = {"excludes": list(MUTABLE_ALERT_FIELDS)}
    return body


def create_elastic(settings: SiemSettings, environ: Mapping[str, str]) -> ElasticSiemConnector:
    """Factory registered as ``elastic``. The API key comes from ``siem.token_env``."""
    return ElasticSiemConnector(open_client(settings, environ), settings.elastic)


def open_client(settings: SiemSettings, environ: Mapping[str, str]) -> ElasticClient:
    """The client both elastic adapters use: address from settings, key from the environment."""
    try:
        base_url = validate_http_base_url(settings.base_url)
    except ValueError as error:
        raise ConfigError(f"Setting 'siem.base_url' {error}") from None
    api_key = read_secret(settings.token_env, environ)
    return ElasticClient(base_url, api_key, settings.verify_tls, settings.timeout_seconds)
