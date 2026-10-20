"""Small, bounded LLM input for L1 and the Web specialist (#91, docs/llm-policy.md 5).

SIEM results and Ticket alerts are summarized before they reach a prompt: a count,
the most frequent rule IDs, the first and last time, and a few representative
records with only the fields a verdict needs. A Web flow becomes rows of four
columns. ``fit_to_limit`` then measures the input the way the LLM call builds it
and drops shown records until it fits ``[l1] max_input_chars``; what it drops is
counted in the summary's ``omitted``. An input that still does not fit is not sent.

The model may cite only what it was shown, so ``Visible`` collects the IDs left in
the final input and the callers check every evidence reference against it.

Everything here is data: log strings are cut, never interpreted, and the caller's
LLM call still wraps the whole input in the untrusted-data delimiter.
"""

from collections import Counter
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from soc.llm.prompts import format_untrusted_data, load_prompt
from soc.normalize.ids import alert_id_for, event_id_for

# docs/llm-policy.md 5: one string field is cut at 2,000 characters.
TEXT_LIMIT = 2_000
# Room for the field path and rule the LLM call adds when it retries once.
RETRY_MARGIN = 500

# The alert being decided, or one of the Ticket's alerts.
ALERT_FIELDS = (
    "alert_id",
    "time",
    "severity_id",
    "rule_id",
    "rule_name",
    "src_ip",
    "src_port",
    "dst_ip",
    "dst_port",
    "host",
    "user",
    "http_url",
    "http_status",
    "techniques",
    "raw_ids",
    "src_asset",
    "dst_asset",
    "user_info",
    "count",
    "first_seen",
    "last_seen",
)
# A representative SIEM record: when, which rule, between whom, and its IDs.
RECORD_FIELDS = (
    "alert_id",
    "time",
    "rule_id",
    "rule_name",
    "src_ip",
    "dst_ip",
    "http_url",
    "raw_ids",
)
EVENT_FIELDS = ("event_id", "time", "src_ip", "dst_ip", "http_url", "http_status", "raw_ids")
# One HTTP flow line. Method, User-Agent and size are left out to keep a full
# demo flow inside the limit (#91); the request and its response code remain.
FLOW_COLUMNS = ("event_id", "time", "http_url", "http_status")

RECORDS = "records"
OMITTED = "omitted"


def cut(value: Any) -> Any:
    """``value`` with every string cut to ``TEXT_LIMIT`` characters."""
    if isinstance(value, str):
        return value[:TEXT_LIMIT]
    if isinstance(value, Mapping):
        return {key: cut(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [cut(item) for item in value]
    return value


def _dump(record: Any) -> Mapping[str, Any]:
    return record.model_dump(mode="json") if hasattr(record, "model_dump") else record


def alert_view(alert: Any) -> dict[str, Any]:
    """The alert fields a verdict needs. ``unmapped`` and ``extensions`` stay out."""
    data = _dump(alert)
    return {name: cut(data.get(name)) for name in ALERT_FIELDS}


def record_view(record: Any) -> dict[str, Any]:
    data = _dump(record)
    fields = RECORD_FIELDS if "alert_id" in data else EVENT_FIELDS
    return {name: cut(data.get(name)) for name in fields}


def ticket_view(ticket: Mapping[str, Any], fields: Sequence[str]) -> dict[str, Any]:
    """``fields`` of a Ticket, with its alert list replaced by a count."""
    view = {name: cut(ticket[name]) for name in fields if name != "alert_ids"}
    view["alert_count"] = len(ticket.get("alert_ids", ()))
    return view


def similar_ticket_view(item: Mapping[str, Any]) -> dict[str, Any]:
    """A decided Ticket as context: what it was and how it was decided."""
    ticket = item["ticket"]
    verdict = ticket.get("verdict") or {}
    return {
        "ticket": ticket_view(
            ticket, ("ticket_id", "origin", "status", "handling_type", "entities")
        )
        | {
            "verdict": {
                "verdict": verdict.get("verdict"),
                "confidence": verdict.get("confidence"),
                "summary": cut(verdict.get("summary")),
            }
        },
        "score": item["score"],
    }


def _distance(time: int | None, at: Sequence[int]) -> int:
    if time is None or not at:
        return 0
    return min(abs(time - point) for point in at)


def summarize_records(
    records: Sequence[Mapping[str, Any]],
    *,
    total: int,
    not_normalized: int,
    top_rules: int,
    max_records: int,
    at: Sequence[int],
) -> dict[str, Any]:
    """Count, rule counts, first and last time, and representative records.

    One record per frequent rule first (the one closest to ``at``), then the
    closest of the rest, up to ``max_records``.
    """
    rules = Counter(record.get("rule_id") for record in records if record.get("rule_id"))
    names = {record.get("rule_id"): record.get("rule_name") for record in records}
    top = rules.most_common(top_rules)
    times = [record["time"] for record in records if record.get("time") is not None]

    by_distance = sorted(records, key=lambda record: _distance(record.get("time"), at))
    chosen: list[Mapping[str, Any]] = []
    for rule_id, _count in top:
        first = next(record for record in by_distance if record.get("rule_id") == rule_id)
        if len(chosen) < max_records:
            chosen.append(first)
    for record in by_distance:
        if len(chosen) >= max_records:
            break
        if not any(record is picked for picked in chosen):
            chosen.append(record)
    chosen.sort(key=lambda record: record.get("time") or 0)

    shown = [record_view(record) for record in chosen]
    return {
        "total": total,
        "not_normalized": not_normalized,
        "first_time": min(times) if times else None,
        "last_time": max(times) if times else None,
        "rules": [
            {"rule_id": rule_id, "rule_name": cut(names.get(rule_id)), "count": count}
            for rule_id, count in top
        ],
        "other_rule_count": max(0, len(rules) - len(top)),
        RECORDS: shown,
        OMITTED: total - len(shown),
    }


def summarize_siem(
    records: Sequence[Mapping[str, Any]],
    store: Any,
    *,
    top_rules: int,
    max_records: int,
    at: Sequence[int],
) -> dict[str, Any]:
    """Summarize C2 records from the SIEM MCP by their stored normalized record.

    The SIEM's own fields are never read: the stored C3/C13 of the same source
    record gives the rule and the entities, whichever SIEM sent it (D-037). A
    record with no stored normalized form is only counted.
    """
    stored = []
    for record in records:
        source_id = record["source_record_id"]
        if record.get("kind") == "event":
            found = store.get_event_record(event_id_for(source_id))
        else:
            found = store.get_alert_record(alert_id_for(source_id))
        if found is not None:
            stored.append(_dump(found))
    return summarize_records(
        stored,
        total=len(records),
        not_normalized=len(records) - len(stored),
        top_rules=top_rules,
        max_records=max_records,
        at=at,
    )


def summarize_alerts(
    alerts: Sequence[Any], *, top_rules: int, max_records: int, at: Sequence[int]
) -> dict[str, Any]:
    """A Ticket's alerts in the same summary shape, shown with the alert fields."""
    dumped = [_dump(alert) for alert in alerts]
    summary = summarize_records(
        dumped,
        total=len(dumped),
        not_normalized=0,
        top_rules=top_rules,
        max_records=max_records,
        at=at,
    )
    shown_ids = {record["alert_id"] for record in summary[RECORDS]}
    summary[RECORDS] = [
        alert_view(alert)
        for alert in sorted(dumped, key=lambda alert: alert["time"])
        if alert["alert_id"] in shown_ids
    ]
    return summary


def evidence_request_view(
    request: Mapping[str, Any],
    store: Any,
    *,
    top_rules: int,
    max_records: int,
    at: Sequence[int],
) -> dict[str, Any]:
    """One C22 result as the model sees it: Lookup as is, SIEM summarized.

    A specialist result is shown once, as the input's ``finding``.
    """
    params = request.get("params") or {}
    result = request.get("result")
    if request.get("request_type") == "siem_mcp" and result is not None:
        result = summarize_siem(
            result.get("records", []), store, top_rules=top_rules, max_records=max_records, at=at
        )
    elif request.get("request_type") == "specialist_agent":
        result = None
    return {
        "request_id": request.get("request_id"),
        "request_type": request.get("request_type"),
        "status": request.get("status"),
        "params": {
            key: cut(params[key])
            for key in ("entity", "kind", "start_at", "end_at", "at")
            if key in params
        },
        "result": cut(result),
    }


def _drop_rank(status: int | None) -> int:
    """Flow lines dropped first: 4xx, then any other non-2xx, 2xx last (#91)."""
    if status is not None and 400 <= status < 500:
        return 2
    if status is None or not 200 <= status < 300:
        return 1
    return 0


def flow_view(src_ip: str, events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """One source's HTTP requests as rows of ``FLOW_COLUMNS``, oldest first."""
    ordered = sorted(events, key=lambda event: (event["time"], event["event_id"]))
    return {
        "src_ip": src_ip,
        "columns": list(FLOW_COLUMNS),
        "rows": [[cut(event.get(name)) for name in FLOW_COLUMNS] for event in ordered],
        "total": len(ordered),
        OMITTED: 0,
    }


@dataclass
class Pool:
    """Shown items that may be dropped, worst first by ``rank``; ``owner[OMITTED]`` counts them.

    Pools are emptied in the order given to ``fit_to_limit``, each down to ``keep``.
    """

    entries: list[tuple[list, Mapping[str, Any], Any]] = field(default_factory=list)
    rank: Callable[[Any], Any] = lambda item: 0
    keep: int = 0

    def add(self, items: list, owner: Mapping[str, Any]) -> None:
        for item in items:
            self.entries.append((items, owner, item))

    def drop_one(self) -> bool:
        if len(self.entries) <= self.keep:
            return False
        worst = max(range(len(self.entries)), key=lambda index: self.rank(self.entries[index][2]))
        items, owner, item = self.entries.pop(worst)
        items.remove(item)
        owner[OMITTED] += 1
        return True


def record_pool(at: Sequence[int], keep: int = 0) -> Pool:
    """Representative records, farthest from ``at`` first."""
    return Pool(rank=lambda record: _distance(record.get("time"), at), keep=keep)


def flow_pool(at: Sequence[int]) -> Pool:
    """Flow rows: 4xx, then other non-2xx, then 2xx; farthest from ``at`` first in each."""
    time_at = FLOW_COLUMNS.index("time")
    status_at = FLOW_COLUMNS.index("http_status")
    return Pool(rank=lambda row: (_drop_rank(row[status_at]), _distance(row[time_at], at)))


def input_size(prompt_text: str, data: object) -> int:
    """Characters the LLM call sends: system prompt plus the delimited data."""
    return len(prompt_text) + len(format_untrusted_data(data))


def fit_to_limit(
    prompt_path: str | Path, data: dict[str, Any], limit: int, pools: Iterable[Pool]
) -> bool:
    """Drop shown records in place until the input fits ``limit``; False if it never does.

    When anything was dropped, ``data["input_trimmed"]`` is true.
    """
    prompt_text = load_prompt(prompt_path).text
    budget = limit - RETRY_MARGIN
    pools = list(pools)
    data["input_trimmed"] = False
    while input_size(prompt_text, data) > budget:
        if not any(pool.drop_one() for pool in pools if pool.entries):
            return False
        data["input_trimmed"] = True
    return True


@dataclass
class Visible:
    """The evidence IDs the model was shown, the only ones it may cite (#91)."""

    alerts: set[str] = field(default_factory=set)
    events: set[str] = field(default_factory=set)
    raw: set[str] = field(default_factory=set)

    def add_records(self, records: Iterable[Mapping[str, Any]]) -> None:
        for record in records:
            if record.get("alert_id"):
                self.alerts.add(record["alert_id"])
            if record.get("event_id"):
                self.events.add(record["event_id"])
            self.raw.update(record.get("raw_ids") or ())

    def add_summary(self, summary: Mapping[str, Any] | None) -> None:
        if isinstance(summary, Mapping) and isinstance(summary.get(RECORDS), list):
            self.add_records(summary[RECORDS])

    def add_flow(self, flow: Mapping[str, Any]) -> None:
        self.events.update(row[0] for row in flow["rows"])

    def add_finding(self, finding: Mapping[str, Any] | None) -> None:
        for reference in (finding or {}).get("evidence", ()):
            target = {"alert": self.alerts, "event": self.events, "raw": self.raw}.get(
                reference["ref_type"]
            )
            if target is not None:
                target.add(reference["ref_id"])

    def allows(self, ref_type: str, ref_id: str) -> bool:
        target = {"alert": self.alerts, "event": self.events, "raw": self.raw}.get(ref_type)
        return target is not None and ref_id in target
