"""elastic SIEM MCP adapter: reads Elasticsearch + Kibana Security (28, 42, D-035, D-037, #99).

The same ``siem.adapter = "elastic"`` setting selects this adapter and the unnumbered
connector. Requests, hit conversion and the API key come from the connector
module, so a document gets the same ``source_record_id`` here as at ingest.

One query becomes one ``POST /<index>/_search``, written as a structured query
(never a query string), so an entity value is only ever a term value:

- index: ``[siem.elastic] alert_index`` for alerts, ``event_index`` for events.
- entity: ip -> ``source.address``, or also ``destination.ip`` when the value is
  an IP (a term on an ip field with any other value is an Elasticsearch error);
  host -> ``host.name``; user -> ``user.name``. Other types read nothing.
- time: events use ``@timestamp``. Alerts use ``kibana.alert.original_time`` (the
  source event's time, which the alias table and the L1 window also use), or
  ``@timestamp`` when an alert has none. Kibana writes an alert a rule interval or
  more after its event, so ``@timestamp`` alone would push it out of the window.
  Both ends count, oldest first, at most ``limit`` records.

Alert fields Kibana changes later (``MUTABLE_ALERT_FIELDS``) are left out, as at
ingest. A hit that cannot become C2 is skipped and only counted in the log.
Any failed request raises ``SiemAdapterError``, even no connection or no answer
in time: the connector's ``ElasticError`` does not yet tell those apart.

Only reads: ``POST /<index>/_search`` for queries and ``GET /<index>/_search?size=0``
for the health check. Hit content may be attacker-written: it is returned as
data and never logged; neither is the API key.
"""

import ipaddress
import logging
from collections.abc import Mapping
from typing import Any

from soc.config import ElasticSiemSettings, SiemSettings
from soc.ingest.siem.base import HealthStatus
from soc.ingest.siem.elastic import (
    ALERT_SCENARIO,
    EVENT_SCENARIO,
    MUTABLE_ALERT_FIELDS,
    TIME_FIELD,
    ElasticClient,
    ElasticError,
    ElasticSiemConnector,
    UnusableHitError,
    hit_to_c2,
    open_client,
    search_hits,
)
from soc.l1.mcp.siem.base import SiemAdapterError, SiemQuery

logger = logging.getLogger(__name__)

ORIGINAL_TIME_FIELD = "kibana.alert.original_time"
# Search-time field for sorting alerts: the first of ``params.fields`` a document has.
ALERT_TIME_RUNTIME_FIELD = "soc_alert_time"
FIRST_PRESENT_DATE_SCRIPT = (
    "for (def field : params.fields) { "
    "if (doc.containsKey(field) && doc[field].size() > 0) { "
    "emit(doc[field].value.toInstant().toEpochMilli()); break; } }"
)
ENTITY_FIELDS = {"host": "host.name", "user": "user.name"}
IP_FIELDS = ("source.address", "destination.ip")


def _term(field: str, value: str) -> dict[str, Any]:
    return {"term": {field: {"value": value}}}


def _is_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value)
    except ValueError:
        return False
    # An ip field does not take a zone (``fe80::1%eth0``).
    return getattr(address, "scope_id", None) is None


def _entity_clause(entity_type: str, value: str) -> dict[str, Any] | None:
    if entity_type == "ip":
        if not _is_ip(value):
            return _term(IP_FIELDS[0], value)
        should = [_term(field, value) for field in IP_FIELDS]
        return {"bool": {"should": should, "minimum_should_match": 1}}
    field = ENTITY_FIELDS.get(entity_type)
    return None if field is None else _term(field, value)


def _range(field: str, query: SiemQuery) -> dict[str, Any]:
    bounds = {"gte": query.start_at, "lte": query.end_at, "format": "epoch_millis"}
    return {"range": {field: bounds}}


def search_body(query: SiemQuery) -> dict[str, Any] | None:
    """The ``_search`` body for ``query``, or None when the entity type is not held here."""
    entity = _entity_clause(query.entity.type, query.entity.value)
    if entity is None:
        return None
    body: dict[str, Any] = {"size": query.limit, "track_total_hits": False}
    if query.kind == "alert":
        without_original = {
            "bool": {
                "must_not": [{"exists": {"field": ORIGINAL_TIME_FIELD}}],
                "filter": [_range(TIME_FIELD, query)],
            }
        }
        window = {
            "bool": {
                "should": [_range(ORIGINAL_TIME_FIELD, query), without_original],
                "minimum_should_match": 1,
            }
        }
        body["runtime_mappings"] = {
            ALERT_TIME_RUNTIME_FIELD: {
                "type": "date",
                "script": {
                    "source": FIRST_PRESENT_DATE_SCRIPT,
                    "params": {"fields": [ORIGINAL_TIME_FIELD, TIME_FIELD]},
                },
            }
        }
        body["sort"] = [{ALERT_TIME_RUNTIME_FIELD: {"order": "asc"}}]
        body["_source"] = {"excludes": list(MUTABLE_ALERT_FIELDS)}
    else:
        window = _range(TIME_FIELD, query)
        # numeric_type "date" gives epoch ms sort values for date and date_nanos fields alike.
        body["sort"] = [{TIME_FIELD: {"order": "asc", "numeric_type": "date"}}]
    body["query"] = {"bool": {"filter": [window, entity]}}
    return body


class ElasticSiemMcp:
    def __init__(self, client: ElasticClient, settings: ElasticSiemSettings):
        self._client = client
        self._indices = {"alert": settings.alert_index, "event": settings.event_index}
        self._scenarios = {"alert": ALERT_SCENARIO, "event": EVENT_SCENARIO}
        # Health is the connector's check: the same two indices, the same probe.
        self._connector = ElasticSiemConnector(client, settings)

    def query(self, query: SiemQuery) -> tuple[Mapping[str, Any], ...]:
        body = search_body(query)
        if body is None:
            return ()
        index = self._indices[query.kind]
        try:
            answer = self._client.search(index, body)
            hits = search_hits(answer)
        except ElasticError as error:
            # ElasticError does not say whether Elasticsearch was reached, so every
            # failure is an adapter error until the connector tells the two apart (#111).
            raise SiemAdapterError(str(error)) from None
        records: list[dict[str, Any]] = []
        reasons: list[str] = []
        for hit in hits[: query.limit]:
            if not isinstance(hit, dict):
                reasons.append("is not an object")
                continue
            try:
                records.append(hit_to_c2(hit, query.kind, self._scenarios[query.kind]))
            except UnusableHitError as reason:
                reasons.append(str(reason))
        if reasons:
            logger.warning(
                "Skipped %d Elasticsearch hit(s) from %s that cannot become C2: %s",
                len(reasons),
                index,
                ", ".join(sorted(set(reasons))),
            )
        return tuple(records)

    def health_check(self) -> HealthStatus:
        return self._connector.health_check()


def create_elastic_mcp(settings: SiemSettings, environ: Mapping[str, str]) -> ElasticSiemMcp:
    """Factory registered as ``elastic``. The API key comes from ``siem.token_env``."""
    return ElasticSiemMcp(open_client(settings, environ), settings.elastic)
