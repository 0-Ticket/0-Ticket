"""A fake Elasticsearch for the elastic adapter tests (#99). Never a real ES.

It serves ``GET|POST /<index>/_search`` over ``http.server`` for the hits it is
given and records every request, so tests can check what the adapter sent. It
understands only the query DSL the adapters write (``bool``, ``range``,
``exists``, ``ids``, ``term``, ``match_all``) and answers 400 to anything else,
including a sort on ``_id`` (Elasticsearch 8+ refuses it by default). ``range``
works on the date fields in ``DATE_FIELDS``. A sort may also use a date runtime
field whose script is ``FIRST_PRESENT_DATE_SCRIPT`` (the first of
``params.fields`` a document has), the one runtime script the SIEM MCP sends.

Hits are ``{"_index", "_id", "_source"}`` dicts as in a ``_search`` answer. The
sort time is ``_source["@timestamp"]``, or a test-only ``_timestamp`` for a hit
whose ``_source`` is not an object.
"""

import json
import socket
import threading
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "elastic"
ALERT_INDEX = ".alerts-security.alerts-*"
EVENT_INDEX = "logs-*"
API_KEY = "fake-elastic-api-key-not-a-secret"
TIME_FIELD = "@timestamp"
ORIGINAL_TIME_FIELD = "kibana.alert.original_time"
DATE_FIELDS = frozenset({TIME_FIELD, ORIGINAL_TIME_FIELD})
# A copy, not an import: a change to the adapter's script must be looked at here too.
FIRST_PRESENT_DATE_SCRIPT = (
    "for (def field : params.fields) { "
    "if (doc.containsKey(field) && doc[field].size() > 0) { "
    "emit(doc[field].value.toInstant().toEpochMilli()); break; } }"
)


def load_hits(name: str) -> list[dict[str, Any]]:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def to_ms(text: str) -> int:
    return round(datetime.fromisoformat(text.replace("Z", "+00:00")).timestamp() * 1000)


def unreachable_url() -> str:
    """An http URL nothing listens on."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}"


@dataclass(frozen=True)
class Request:
    method: str
    path: str
    query: dict[str, list[str]]
    body: dict[str, Any] | None
    authorization: str | None


class _BadQuery(Exception):
    pass


def _hit_time(hit: dict[str, Any]) -> int | None:
    source = hit["_source"]
    if isinstance(source, dict) and isinstance(source.get(TIME_FIELD), str):
        return to_ms(source[TIME_FIELD])
    if "_timestamp" in hit:
        return to_ms(hit["_timestamp"])
    return None


def _values(view: Any, parts: list[str]) -> list[Any]:
    """Values at a dotted path, reading nested objects and dotted keys alike (as ES does)."""
    if not parts:
        return view if isinstance(view, list) else [view]
    if isinstance(view, list):
        return [found for item in view for found in _values(item, parts)]
    if not isinstance(view, dict):
        return []
    found: list[Any] = []
    for cut in range(1, len(parts) + 1):
        key = ".".join(parts[:cut])
        if key in view:
            found.extend(_values(view[key], parts[cut:]))
    return found


def _field_values(hit: dict[str, Any], field: str) -> list[Any]:
    if field == TIME_FIELD:
        time = _hit_time(hit)
        return [] if time is None else [time]
    values = _values(hit["_source"], field.split("."))
    if field in DATE_FIELDS:
        return [to_ms(value) for value in values if isinstance(value, str)]
    return values


def _matches(hit: dict[str, Any], clause: dict[str, Any]) -> bool:
    if len(clause) != 1:
        raise _BadQuery("a query clause holds exactly one key")
    ((kind, spec),) = clause.items()
    if kind == "match_all":
        return True
    if kind == "bool":
        return _matches_bool(hit, spec)
    if kind == "ids":
        return hit["_id"] in spec["values"]
    if kind == "exists":
        return bool(_field_values(hit, spec["field"]))
    if kind == "term":
        ((field, value),) = spec.items()
        if isinstance(value, dict):
            value = value["value"]
        return any(str(found) == str(value) for found in _field_values(hit, field))
    if kind == "range":
        ((field, bounds),) = spec.items()
        if field not in DATE_FIELDS or bounds.get("format") != "epoch_millis":
            raise _BadQuery("the fake only ranges its date fields in epoch_millis")
        values = _field_values(hit, field)
        return any(
            ("gte" not in bounds or value >= int(bounds["gte"]))
            and ("gt" not in bounds or value > int(bounds["gt"]))
            and ("lte" not in bounds or value <= int(bounds["lte"]))
            and ("lt" not in bounds or value < int(bounds["lt"]))
            for value in values
        )
    raise _BadQuery(f"unsupported query {kind}")


def _matches_bool(hit: dict[str, Any], spec: dict[str, Any]) -> bool:
    unknown = set(spec) - {"filter", "must", "should", "must_not", "minimum_should_match"}
    if unknown:
        raise _BadQuery("unsupported bool key")
    for key in ("filter", "must"):
        if not all(_matches(hit, clause) for clause in spec.get(key, [])):
            return False
    if any(_matches(hit, clause) for clause in spec.get("must_not", [])):
        return False
    should = spec.get("should", [])
    if should:
        needed = spec.get("minimum_should_match", 1)
        if sum(_matches(hit, clause) for clause in should) < needed:
            return False
    return True


def _runtime_fields(body: dict[str, Any]) -> dict[str, list[str]]:
    """Runtime field name -> the date fields its script tries, in order."""
    fields: dict[str, list[str]] = {}
    for name, spec in body.get("runtime_mappings", {}).items():
        script = spec["script"]
        if spec.get("type") != "date" or script.get("source") != FIRST_PRESENT_DATE_SCRIPT:
            raise _BadQuery("the fake only runs the first-present date script")
        tried = script["params"]["fields"]
        if not set(tried) <= DATE_FIELDS:
            raise _BadQuery("the fake only reads its date fields in a script")
        fields[name] = tried
    return fields


def _sort_field(sort: list[Any], runtime: dict[str, list[str]]) -> list[str] | None:
    """The date fields the one sort key reads (first present wins), or None without a sort."""
    if not sort:
        return None
    if len(sort) != 1:
        raise _BadQuery("the fake sorts on one key")
    entry = sort[0]
    field = entry if isinstance(entry, str) else next(iter(entry))
    if field == TIME_FIELD:
        return [TIME_FIELD]
    if field in runtime:
        return runtime[field]
    raise _BadQuery(f"the fake only sorts on {TIME_FIELD} or a runtime field; {field} is refused")


def _sort_time(hit: dict[str, Any], fields: list[str]) -> int:
    for field in fields:
        values = _field_values(hit, field)
        if values:
            return values[0]
    return 0


class FakeElasticsearch:
    """Use as a context manager; ``url`` is set while it runs."""

    def __init__(self, indices: dict[str, list[dict[str, Any]]], api_key: str = API_KEY):
        self.indices = indices
        self.api_key = api_key
        self.requests: list[Request] = []
        # Set to answer every request with this HTTP status (e.g. 403).
        self.status_override: int | None = None
        self._server: ThreadingHTTPServer | None = None
        self.url = ""

    def __enter__(self) -> "FakeElasticsearch":
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802 (http.server naming)
                fake._handle(self)

            def do_POST(self) -> None:  # noqa: N802
                fake._handle(self)

            def do_PUT(self) -> None:  # noqa: N802
                fake._handle(self)

            def do_DELETE(self) -> None:  # noqa: N802
                fake._handle(self)

            def log_message(self, *args: Any) -> None:
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self._server.server_address[1]}"
        threading.Thread(
            target=self._server.serve_forever, kwargs={"poll_interval": 0.01}, daemon=True
        ).start()
        return self

    def __exit__(self, *exc: Any) -> None:
        assert self._server is not None
        self._server.shutdown()
        self._server.server_close()

    def _handle(self, handler: BaseHTTPRequestHandler) -> None:
        parts = urlsplit(handler.path)
        length = int(handler.headers.get("Content-Length") or 0)
        raw = handler.rfile.read(length) if length else b""
        body = json.loads(raw) if raw else None
        request = Request(
            method=handler.command,
            path=parts.path,
            query=parse_qs(parts.query),
            body=body,
            authorization=handler.headers.get("Authorization"),
        )
        self.requests.append(request)
        status, answer = self._answer(request)
        data = json.dumps(answer).encode("utf-8")
        handler.send_response(status)
        handler.send_header("Content-Type", "application/json")
        handler.send_header("Content-Length", str(len(data)))
        handler.end_headers()
        handler.wfile.write(data)

    def _answer(self, request: Request) -> tuple[int, dict[str, Any]]:
        if self.status_override is not None:
            return self.status_override, {"error": {"type": "forced"}}
        if request.authorization != f"ApiKey {self.api_key}":
            return 401, {"error": {"type": "security_exception"}}
        segments = request.path.strip("/").split("/")
        if request.method not in {"GET", "POST"} or len(segments) != 2 or segments[1] != "_search":
            return 405, {"error": {"type": "not_supported_by_fake"}}
        index = unquote(segments[0])
        if index not in self.indices:
            return 404, {"error": {"type": "index_not_found_exception"}}
        body = request.body or {}
        size = int(request.query.get("size", [body.get("size", 10)])[0])
        try:
            sort_fields = _sort_field(body.get("sort", []), _runtime_fields(body))
            query = body.get("query", {"match_all": {}})
            matched = [hit for hit in self.indices[index] if _matches(hit, query)]
        except (_BadQuery, KeyError, TypeError, ValueError) as error:
            return 400, {"error": {"type": "parsing_exception", "reason": str(error)}}
        if sort_fields is not None:
            # sorted() is stable: same-time hits keep their fixture order.
            matched = sorted(matched, key=lambda hit: _sort_time(hit, sort_fields))
        hits = []
        for hit in matched[:size]:
            answer = {key: hit[key] for key in ("_index", "_id", "_source")}
            if sort_fields is not None:
                answer["sort"] = [_sort_time(hit, sort_fields)]
            hits.append(answer)
        return 200, {"hits": {"total": {"value": len(matched), "relation": "eq"}, "hits": hits}}
