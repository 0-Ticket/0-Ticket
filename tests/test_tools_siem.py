"""SIEM 조회 도구(#212): query_siem, count_siem.

네트워크 없이 돈다. ES 응답은 tests/fixtures/siem/의 손으로 만든 JSON이고, httpx.MockTransport에
FakeElk(tests/fake_siem.py)를 넣는다. FakeElk는 POST /<index>/_search 밖의 요청을 받으면
violations에 남기고, elk 픽스처가 테스트 끝에 그것이 비었는지 확인한다.
"""

import asyncio
import itertools
import json
import re
import tomllib
from pathlib import Path
from typing import Any

import httpx
import pytest
from fake_model import FakeModel, tool_outputs
from fake_siem import ELK_KEY, ELK_URL, FakeElk, chunks, fixture, ok, status
from test_agent_core import ALERT_ID, CONFIG, make_task, no_sleep
from tool_helpers import Caller, body_chars, new_recorder, parse

from soc.agent.agent_log import MemoryLogSink
from soc.agent.config import load_config
from soc.agent.runner import run_task
from soc.ids import siem_ref_key
from soc.tools import (
    CUT_MARK,
    RESULT_CLOSE,
    ToolConfigError,
    ToolRegistry,
    default_registry,
    tool_error_text,
)
from soc.tools import siem as siem_mod
from soc.tools.siem import (
    FIELD_MAX_CHARS,
    FILTERS,
    TARGET_FIELDS,
    TARGET_FILTERS,
    TARGET_NAMES,
    siem_tools,
)

REPO = Path(__file__).resolve().parents[1]
START = 1_793_750_400_000  # 2026-11-04T00:00:00Z
END = START + 86_400_000
DAY = 86_400_000
WEB_INDEX = "logs-nginx.access-*,logs-apache.access-*"
TARGETS = [
    {"name": "alerts", "index": ".alerts-security.alerts-default", "time_field": "@timestamp"},
    {"name": "web_access", "index": WEB_INDEX, "time_field": "@timestamp"},
    {"name": "cloudtrail", "index": "logs-aws.cloudtrail-*", "time_field": "@timestamp"},
    {"name": "evidence", "index": "logs-*,filebeat-*", "time_field": "@timestamp"},
]
SIEM = {
    "url_env": "ELK_URL",
    "api_key_env": "ELK_API_KEY",
    "connect_timeout_seconds": 5,
    "read_timeout_seconds": 10,
    "deadline_seconds": 15,
    "max_bytes": 5_242_880,
    "targets": TARGETS,
}
TOOLS = ["query_siem", "count_siem"]
# 모델 입력·detail·Agent Log에 나오면 안 되는 것: 키, ES 주소, 응답 본문, 쿼리 원문
LEAKS = (
    ELK_KEY,
    "elk.example.com",
    "elk-internal",
    "security_exception",
    "all shards failed",
    "ApiKey",
    '"bool"',
    "epoch_millis",
    "_search",
)


def config(
    *, chars: int = 6_000, siem: dict[str, Any] | None = None, stage: str = "l1"
) -> dict[str, Any]:
    agent = {**CONFIG["agent"], stage: {**CONFIG["agent"][stage], "max_tool_result_chars": chars}}
    agent[stage]["max_turns"] = 6
    return {
        **CONFIG,
        "agent": agent,
        "tools": {
            **CONFIG["tools"],
            "siem": SIEM if siem is None else siem,
            "allowed": {stage: TOOLS},
        },
    }


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ELK_URL", ELK_URL)
    monkeypatch.setenv("ELK_API_KEY", ELK_KEY)


@pytest.fixture
def elk(env: None):
    fake = FakeElk()
    yield fake
    assert fake.violations == []


def registry(fake: FakeElk, clock: Any = None) -> ToolRegistry:
    kwargs: dict[str, Any] = {"transport": fake.transport()}
    if clock is not None:
        kwargs["clock"] = clock
    return ToolRegistry(siem_tools(**kwargs))


def caller(fake: FakeElk, cfg: dict[str, Any] | None = None, clock: Any = None) -> Caller:
    return Caller(registry(fake, clock), cfg or config())


def call(c: Caller, name: str, arguments: dict[str, Any]) -> str:
    return asyncio.run(c(name, arguments))


def query(**kwargs: Any) -> dict[str, Any]:
    return {"target": "web_access", "start_ms": START, "end_ms": END, **kwargs}


def count(**kwargs: Any) -> dict[str, Any]:
    return {"target": "web_access", "start_ms": START, "end_ms": END, "field": "url_path", **kwargs}


def failure(row: dict[str, Any]) -> dict[str, Any]:
    """tool 줄 details 중 오류에 관한 칸만(attempt·task 등은 뺀다)."""
    return {k: row["details"][k] for k in ("failure", "reason", "blocked") if k in row["details"]}


def leaked(text: str) -> list[str]:
    return [word for word in LEAKS if word in text]


# query_siem


def test_query_web_access_builds_the_query_and_shapes_hits(elk: FakeElk) -> None:
    elk.add(ok("search_web_access.json"))
    c = caller(elk)
    out = call(c, "query_siem", query(source_ip="203.0.113.10"))
    body = parse(out)

    request = elk.requests[0]
    assert request.method == "POST"
    assert request.url.path == f"/{WEB_INDEX}/_search"
    assert request.headers["authorization"] == f"ApiKey {ELK_KEY}"
    assert elk.bodies()[0] == {
        "size": 20,
        "query": {
            "bool": {
                "filter": [
                    {"range": {"@timestamp": {"gte": START, "lt": END, "format": "epoch_millis"}}},
                    {"term": {"source.ip": "203.0.113.10"}},
                ]
            }
        },
        "sort": [{"@timestamp": {"order": "desc", "unmapped_type": "date"}}],
        "_source": ["@timestamp", *TARGET_FIELDS["web_access"]],
        "track_total_hits": 10_000,
    }

    assert body["call_id"].startswith("agl_")
    assert body["source"] == "siem"
    assert body["schema"] == "ecs"
    assert body["target"] == "web_access"
    assert body["total"] == 3 and body["total_relation"] == "eq"
    assert body["truncated"] is False and body["omitted"] == 0
    first, second, third = body["hits"]
    assert first["siem_ref"] == ".ds-logs-nginx.access-default-2026.11.04-000001/web-doc-0001"
    assert first["fields"]["source.ip"] == "203.0.113.10"
    assert first["fields"]["http.response.status_code"] == 401
    assert first["fields"]["http.response.body.bytes"] == 512
    # 반환 필드 밖의 값(event.original, source.geo)은 버린다
    assert "event.original" not in first["fields"]
    assert not any(key.startswith("source.geo") for key in first["fields"])
    # 직렬화 길이(… 포함)가 FIELD_MAX_CHARS 이하가 되게 자르고 경로를 적는다
    assert dlen(first["fields"]["url.query"]) <= siem_mod.FIELD_MAX_CHARS
    assert first["fields"]["url.query"].endswith("…")
    assert first["truncated_fields"] == ["url.query"]
    # 점이 든 키와 중첩된 키를 모두 읽는다
    assert second["fields"]["url.path"] == "/admin"
    assert second["fields"]["user.name"] == "test-user"
    assert second["fields"]["http.response.status_code"] == 403
    assert "truncated_fields" not in second
    # 없는 필드는 넣지 않는다
    assert set(third["fields"]) == {
        "@timestamp",
        "source.ip",
        "url.path",
        "http.request.method",
        "http.response.status_code",
    }
    # 장부에는 call_id만
    assert c.session.evidence_ids == {body["call_id"]}


def test_query_alerts_reads_kibana_alert_fields(elk: FakeElk) -> None:
    elk.add(ok("search_alerts.json"))
    c = caller(elk)
    args = {"target": "alerts", "start_ms": START, "end_ms": END}
    body = parse(call(c, "query_siem", {**args, "rule_name": "Unusual Login Activity"}))
    sent = elk.bodies()[0]
    assert elk.requests[0].url.path == "/.alerts-security.alerts-default/_search"
    assert sent["query"]["bool"]["filter"][1] == {
        "term": {"kibana.alert.rule.name": "Unusual Login Activity"}
    }
    assert body["total"] == 10_000 and body["total_relation"] == "gte"
    flat, nested = body["hits"]
    assert flat["fields"]["kibana.alert.rule.name"].startswith("Multiple Logon Failure")
    assert flat["fields"]["kibana.alert.severity"] == "medium"
    assert flat["fields"]["event.action"] == "logon-failed"
    assert "kibana.alert.original_event" not in json.dumps(flat)
    assert nested["fields"]["kibana.alert.rule.name"] == "Unusual Login Activity"
    assert nested["fields"]["kibana.alert.severity"] == "high"
    assert nested["fields"]["kibana.alert.risk_score"] == 73


def test_query_cloudtrail(elk: FakeElk) -> None:
    elk.add(ok("search_cloudtrail.json"))
    c = caller(elk)
    args = {"target": "cloudtrail", "start_ms": START, "end_ms": END}
    body = parse(call(c, "query_siem", {**args, "event_action": "ConsoleLogin", "limit": 5}))
    sent = elk.bodies()[0]
    assert elk.requests[0].url.path == "/logs-aws.cloudtrail-*/_search"
    assert sent["size"] == 5
    assert sent["query"]["bool"]["filter"][1] == {"term": {"event.action": "ConsoleLogin"}}
    hit = body["hits"][0]
    assert hit["siem_ref"] == ".ds-logs-aws.cloudtrail-default-2026.11.04-000001/ct-doc-0001"
    assert hit["fields"]["cloud.account.id"] == "111122223333"
    assert hit["fields"]["event.outcome"] == "failure"
    assert not any(key.startswith("aws.") for key in hit["fields"])


def test_siem_ref_is_the_stored_key_for_an_odd_id(elk: FakeElk) -> None:
    # 따옴표·백슬래시·제어문자·한글 _id: 에이전트가 받은 siem_ref는 수집이 raw_records.siem_ref에
    # 넣는 저장 키와 같아야 한다(#277, D-049). 수집 쪽 키 규칙은 test_raw_original이 본다.
    index = ".ds-logs-web-default-2026.11.04-000001"
    doc_id = 'q"b\\s\x01z\x00한글'
    hit = {"_index": index, "_id": doc_id, "_source": {"@timestamp": START + 1000}}
    elk.add(
        httpx.Response(200, json={"hits": {"total": {"value": 1, "relation": "eq"}, "hits": [hit]}})
    )
    body = parse(call(caller(elk), "query_siem", query()))

    assert body["hits"][0]["siem_ref"] == siem_ref_key(f"{index}/{doc_id}")
    assert body["hits"][0]["siem_ref"].isascii()


def test_query_sort_and_filters_in_fixed_order(elk: FakeElk) -> None:
    elk.add(ok("empty.json"))
    c = caller(elk)
    args = query(sort="time_asc", status_code=404, source_ip="198.51.100.0/24", http_method="GET")
    call(c, "query_siem", args)
    sent = elk.bodies()[0]
    assert sent["sort"] == [{"@timestamp": {"order": "asc", "unmapped_type": "date"}}]
    terms = [f["term"] for f in sent["query"]["bool"]["filter"][1:]]
    assert terms == [
        {"source.ip": "198.51.100.0/24"},
        {"http.request.method": "GET"},
        {"http.response.status_code": 404},
    ]


def test_query_uses_only_range_and_term(elk: FakeElk) -> None:
    elk.add(ok("empty.json"))
    c = caller(elk)
    call(c, "query_siem", query(url_path="/a* OR _index:secret", user_name='x" OR "1'))
    sent = json.dumps(elk.bodies()[0])
    for word in ("query_string", "simple_query_string", "wildcard", "regexp", "script", "match"):
        assert word not in sent
    terms = [f["term"] for f in elk.bodies()[0]["query"]["bool"]["filter"][1:]]
    # 모델이 준 값은 term 값 자리에 그대로 들어간다(해석하지 않는다)
    assert terms == [{"user.name": 'x" OR "1'}, {"url.path": "/a* OR _index:secret"}]


def test_zero_hits_is_not_an_error(elk: FakeElk) -> None:
    elk.add(ok("empty.json"))
    c = caller(elk)
    out = call(c, "query_siem", query())
    body = parse(out)
    assert body["hits"] == [] and body["total"] == 0
    assert body["call_id"] in c.session.evidence_ids
    assert c.rows[0]["outcome"] == "ok"


def test_query_drops_hits_from_the_end_to_fit(elk: FakeElk) -> None:
    elk.add(ok("search_large.json"))
    c = caller(elk, config(chars=3_000))
    out = call(c, "query_siem", query(limit=100))
    body = parse(out)
    assert body_chars(out) <= 3_000
    assert body["truncated"] is True
    assert 0 < len(body["hits"]) < 40
    assert body["omitted"] == 40 - len(body["hits"])
    refs = [h["siem_ref"].split("/")[1] for h in body["hits"]]
    assert refs == [f"large-doc-{i:04d}" for i in range(len(refs))]  # 앞에서부터 남긴다


def test_query_with_no_room_for_one_hit_returns_zero_hits(elk: FakeElk) -> None:
    # 300자는 빈 본문(197자)에 siem_ref만 있는 히트(116자)를 더한 313자보다 작다. 그때만 0건이다
    elk.add(ok("search_large.json"))
    c = caller(elk, config(chars=300))
    body = parse(call(c, "query_siem", query()))
    assert body["hits"] == [] and body["truncated"] is True and body["omitted"] == 40


def test_query_with_room_only_for_a_siem_ref_shows_that_one_hit(elk: FakeElk) -> None:
    elk.add(ok("search_large.json"))
    c = caller(elk, config(chars=320))
    out = call(c, "query_siem", query())
    body = parse(out)
    assert body_chars(out) <= 320
    assert body["total"] == 40 and body["truncated"] is True and body["omitted"] == 39
    assert body["hits"] == [
        {"siem_ref": f"{STORED_INDEX}/large-doc-0000", "fields": {}, "fields_omitted": True}
    ]


# 한도보다 큰 히트(#281): 0건으로 숨기지 않고 줄이거나 siem_ref만 보인다

# 실측(docs/notes/281): 한도 350~1,500자에서 wide 히트는 siem_ref만 보이고 3,000자부터 줄여서 보인다
SIEM_REF_ONLY_CHARS = 500

NASTY = '"<' * 150  # 300자. 직렬화하면 큰따옴표 2자, <는 6자가 된다
STORED_INDEX = ".ds-logs-nginx.access-default-2026.11.04-000001"
FIELD_PATH = re.compile(r"[A-Za-z0-9@_.]+(\[\d+\])?")  # 경로 이름만. 값은 들어가지 않는다


def dlen(value: Any) -> int:
    """모델에게 가는 직렬화 길이(registry.dumped_len)."""
    from soc.tools.registry import dumped_len

    return dumped_len(value)


def one_hit(source: dict[str, Any], doc_id: str = "one-doc-0001") -> dict[str, Any]:
    hit = {"_index": STORED_INDEX, "_id": doc_id, "_score": None, "_source": source}
    return {
        "took": 1,
        "timed_out": False,
        "hits": {"total": {"value": 1, "relation": "eq"}, "hits": [hit]},
    }


def respond(elk: FakeElk, data: dict[str, Any]) -> None:
    elk.add(httpx.Response(200, json=data))


def walk_values(value: Any):
    if isinstance(value, dict):
        for item in value.values():
            yield from walk_values(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk_values(item)
    else:
        yield value


def test_oversized_hit_is_shown_not_hidden(elk: FakeElk) -> None:
    elk.add(ok("search_oversized_hit.json"))
    c = caller(elk)  # L1 한도 6,000자
    out = call(c, "query_siem", query())
    body = parse(out)
    assert body["total"] == 1 and len(body["hits"]) == 1 and body["omitted"] == 0
    hit = body["hits"][0]
    assert hit["siem_ref"] == f"{STORED_INDEX}/oversized-doc-0001"
    assert body_chars(out) <= 6_000
    # 값 하나의 직렬화 길이(… 포함)가 FIELD_MAX_CHARS 이하다
    assert all(dlen(v) <= siem_mod.FIELD_MAX_CHARS for v in walk_values(hit["fields"]))
    assert hit["truncated_fields"] == [
        "url.path",
        "url.query",
        "user_agent.original",
        "user.name[0]",
        "user.name[1]",
        "user.name[2]",
        "host.name",
    ]
    assert "fields_omitted" not in hit
    assert c.session.evidence_ids == {body["call_id"]}
    # Agent Log tool 줄에는 모델에게 보인 히트가 남는다(원본 찾기용)
    assert c.rows[0]["output"]["hits"][0]["siem_ref"] == hit["siem_ref"]


@pytest.mark.parametrize(
    "unit",
    ['"<', ">", "가나다", "😀", "\x01", "x", '\\"'],
    ids=["quote-lt", "gt", "hangul", "emoji", "control", "ascii", "backslash-quote"],
)
def test_cut_value_fits_field_max_chars_including_the_cut_mark(elk: FakeElk, unit: str) -> None:
    original = unit * 1_000
    respond(elk, one_hit({"url": {"query": original}, "source": {"ip": "203.0.113.9"}}))
    hit = parse(call(caller(elk), "query_siem", query()))["hits"][0]
    value = hit["fields"]["url.query"]
    assert value.endswith("…") and dlen(value) <= siem_mod.FIELD_MAX_CHARS
    kept = value[:-1]
    assert original.startswith(kept)
    # 가장 긴 앞부분이다: 한 글자 더 남기면 한도를 넘는다
    assert dlen(original[: len(kept) + 1] + "…") > siem_mod.FIELD_MAX_CHARS
    assert hit["truncated_fields"] == ["url.query"]


def test_short_non_ascii_value_is_not_cut(elk: FakeElk) -> None:
    value = "가나다😀" * 20
    respond(elk, one_hit({"url": {"query": value}}))
    hit = parse(call(caller(elk), "query_siem", query()))["hits"][0]
    assert hit["fields"]["url.query"] == value
    assert "truncated_fields" not in hit


def test_long_list_is_cut_to_field_max_items(elk: FakeElk) -> None:
    respond(elk, one_hit({"user": {"name": [f"u{i}" for i in range(5_000)]}}))
    hit = parse(call(caller(elk), "query_siem", query()))["hits"][0]
    names = hit["fields"]["user.name"]
    assert names == [f"u{i}" for i in range(siem_mod.FIELD_MAX_ITEMS)]
    assert hit["truncated_fields"] == ["user.name"]


def test_list_of_exactly_field_max_items_is_kept(elk: FakeElk) -> None:
    respond(elk, one_hit({"user": {"name": [f"u{i}" for i in range(siem_mod.FIELD_MAX_ITEMS)]}}))
    hit = parse(call(caller(elk), "query_siem", query()))["hits"][0]
    assert len(hit["fields"]["user.name"]) == siem_mod.FIELD_MAX_ITEMS
    assert "truncated_fields" not in hit


def test_hit_over_its_share_is_shortened_and_keeps_short_fields(elk: FakeElk) -> None:
    elk.add(ok("search_oversized_hit_wide.json"))
    c = caller(elk, config(chars=3_000))
    out = call(c, "query_siem", query())
    body = parse(out)
    assert body_chars(out) <= 3_000
    assert body["truncated"] is True and body["omitted"] == 0 and len(body["hits"]) == 1
    hit = body["hits"][0]
    assert "fields_omitted" not in hit
    # 짧은 값(시각, IP, 메서드, 상태 코드)은 그대로다
    assert hit["fields"]["@timestamp"] == "2026-11-04T04:00:00.000Z"
    assert hit["fields"]["source.ip"] == "203.0.113.9"
    assert hit["fields"]["http.request.method"] == "GET"
    assert hit["fields"]["http.response.status_code"] == 200
    # 줄인 경로만 적는다(값은 없다). 줄이기 전 자르기 경로도 합쳐진다
    assert hit["truncated_fields"] and all(FIELD_PATH.fullmatch(p) for p in hit["truncated_fields"])
    assert len(hit["truncated_fields"]) == len(set(hit["truncated_fields"]))
    assert "url.query" in hit["truncated_fields"]


def test_hit_that_cannot_be_shortened_keeps_only_its_siem_ref(elk: FakeElk) -> None:
    elk.add(ok("search_oversized_hit_wide.json"))
    c = caller(elk, config(chars=SIEM_REF_ONLY_CHARS))
    out = call(c, "query_siem", query())
    body = parse(out)
    assert body_chars(out) <= SIEM_REF_ONLY_CHARS
    assert body["total"] == 1 and body["truncated"] is True and body["omitted"] == 0
    # 문서는 있었지만 내용을 볼 수 없다. 필드 값은 하나도 없다
    assert body["hits"] == [
        {"siem_ref": f"{STORED_INDEX}/wide-doc-0001", "fields": {}, "fields_omitted": True}
    ]


def test_big_hit_first_does_not_hide_the_small_hits_behind_it(elk: FakeElk) -> None:
    elk.add(ok("search_oversized_then_small.json"))
    c = caller(elk)
    out = call(c, "query_siem", query(limit=100))
    body = parse(out)
    assert body_chars(out) <= 6_000
    refs = [h["siem_ref"].split("/")[1] for h in body["hits"]]
    assert refs == ["big-doc-0000"] + [f"small-doc-{i:04d}" for i in range(1, 9)]
    assert body["total"] == 9 and body["omitted"] == 0 and body["truncated"] is True
    big, *small = body["hits"]
    # 큰따옴표·<로 채운 큰 히트도 L1에서 siem_ref만 남지 않고 줄여서 보인다. 짧은 값은 그대로다
    assert "fields_omitted" not in big and big["truncated_fields"]
    assert big["fields"]["source.ip"] == "203.0.113.9"
    assert big["fields"]["@timestamp"] == "2026-11-04T05:00:00.000Z"
    assert big["fields"]["http.request.method"] == "GET"
    assert big["fields"]["http.response.status_code"] == 200
    assert all(FIELD_PATH.fullmatch(p) for p in big["truncated_fields"])
    assert all("truncated_fields" not in h and "fields_omitted" not in h for h in small)
    assert small[0]["fields"]["source.ip"] == "203.0.113.11"


def test_shortened_hit_can_be_cited_by_call_id(elk: FakeElk) -> None:
    elk.add(ok("search_oversized_hit.json"))

    def cite(outputs: list[str]) -> dict[str, Any]:
        return verdict(ALERT_ID, parse(outputs[0])["call_id"])

    result, model, sink = run(elk, [siem_call(query()), {"final_fn": cite}])
    assert result.ok is True, result.detail
    out = parse(tool_outputs(model.calls[-1]["input"])[0])
    assert len(out["hits"]) == 1
    row = next(r for r in sink.rows if r["kind"] == "tool")
    assert row["output"]["hits"][0]["siem_ref"] == out["hits"][0]["siem_ref"]
    assert out["call_id"] in result.cited_evidence_ids


def test_result_body_cannot_close_the_delimiter(elk: FakeElk) -> None:
    elk.add(ok("search_web_access.json"))
    out = call(caller(elk), "query_siem", query())
    assert out.count(RESULT_CLOSE) == 1
    assert out.endswith(RESULT_CLOSE)


# count_siem


def test_count_returns_top_values(elk: FakeElk) -> None:
    elk.add(ok("terms.json"))
    c = caller(elk)
    out = call(c, "count_siem", count(http_method="GET"))
    body = parse(out)
    sent = elk.bodies()[0]
    assert sent == {
        "size": 0,
        "query": {
            "bool": {
                "filter": [
                    {"range": {"@timestamp": {"gte": START, "lt": END, "format": "epoch_millis"}}},
                    {"term": {"http.request.method": "GET"}},
                ]
            }
        },
        "aggs": {"top": {"terms": {"field": "url.path", "size": 10}}},
        "track_total_hits": True,
    }
    assert body["source"] == "siem" and body["schema"] == "ecs"
    assert body["target"] == "web_access" and body["field"] == "url_path"
    assert body["total"] == 1234
    assert body["other_count"] == 34
    assert body["truncated"] is False
    assert len(body["buckets"]) == 10
    assert body["buckets"][0] == {"value": "/login", "count": 500}
    last = body["buckets"][-1]
    assert len(last["value"]) == 121 and last["value"].endswith("…")
    assert last["value_truncated"] is True
    assert out.count(RESULT_CLOSE) == 1
    assert c.session.evidence_ids == {body["call_id"]}


def test_count_drops_smallest_buckets_to_fit(elk: FakeElk) -> None:
    elk.add(ok("terms.json"))
    c = caller(elk, config(chars=500))
    out = call(c, "count_siem", count())
    body = parse(out)
    assert body_chars(out) <= 500
    assert body["truncated"] is True
    kept = [b["value"] for b in body["buckets"]]
    order = [b["key"] for b in fixture("terms.json")["aggregations"]["top"]["buckets"]]
    assert 0 < len(kept) < 10
    assert kept == order[: len(kept)]  # 건수가 적은 뒤쪽부터 뺐다
    # 뺀 항목의 건수는 other_count에 더한다(보이는 건수 + other_count = 전체)
    shown = sum(b["count"] for b in body["buckets"])
    assert shown + body["other_count"] == 1234


def test_count_alerts_by_severity(elk: FakeElk) -> None:
    elk.add(ok("terms.json"))
    c = caller(elk)
    args = {"target": "alerts", "start_ms": START, "end_ms": END, "field": "alert_severity"}
    call(c, "count_siem", {**args, "alert_severity": "high"})
    sent = elk.bodies()[0]
    assert sent["aggs"]["top"]["terms"]["field"] == "kibana.alert.severity"
    assert sent["query"]["bool"]["filter"][1] == {"term": {"kibana.alert.severity": "high"}}


# 인자 검사


INVALID = [
    ("query_siem", query(target="logs-*")),
    ("query_siem", query(target="cloudtrail_raw")),
    ("query_siem", query(cloud_account_id="111122223333")),  # web_access에 없는 필터
    ("query_siem", query(target="cloudtrail", url_path="/")),
    (
        "query_siem",
        query(
            source_ip="203.0.113.1",
            destination_ip="192.0.2.1",
            user_name="u",
            host_name="h",
            url_path="/",
            http_method="GET",
        ),
    ),  # 필터 6개
    ("query_siem", query(source_ip="not-an-ip")),
    ("query_siem", query(source_ip="203.0.113.300")),
    ("query_siem", query(destination_ip="192.0.2.0/33")),
    ("query_siem", query(end_ms=START + 7 * DAY + 1)),
    ("query_siem", query(end_ms=START)),
    ("query_siem", query(limit=0)),
    ("query_siem", query(limit=101)),
    ("query_siem", query(status_code=600)),
    ("query_siem", query(status_code="404")),
    ("query_siem", query(http_method="GE T")),
    ("query_siem", query(user_name="a" * 201)),
    ("query_siem", query(user_name="")),
    ("query_siem", query(sort="relevance")),
    ("query_siem", query(query="*")),  # 정의에 없는 인자(쿼리 문자열)
    ("query_siem", query(index="secret-*")),
    ("query_siem", {"start_ms": START, "end_ms": END}),
    ("count_siem", count(field="cloud_account_id")),  # web_access에 없는 필드
    ("count_siem", count(field="message")),
    ("count_siem", {"target": "web_access", "start_ms": START, "end_ms": END}),
    ("count_siem", count(target="alerts", field="rule_name", url_path="/")),
]


@pytest.mark.parametrize(("name", "arguments"), INVALID)
def test_invalid_arguments_are_rejected_before_any_request(
    elk: FakeElk, name: str, arguments: dict[str, Any]
) -> None:
    c = caller(elk)
    out = call(c, name, arguments)
    assert out == tool_error_text(name, "invalid_argument")
    assert elk.requests == []


def test_target_removed_from_config_is_invalid(elk: FakeElk) -> None:
    siem = {**SIEM, "targets": [t for t in TARGETS if t["name"] != "cloudtrail"]}
    c = caller(elk, config(siem=siem))
    args = {"target": "cloudtrail", "start_ms": START, "end_ms": END}
    assert call(c, "query_siem", args) == tool_error_text("query_siem", "invalid_argument")
    assert elk.requests == []


def test_five_filters_and_cidr_are_allowed(elk: FakeElk) -> None:
    elk.add(ok("empty.json"))
    c = caller(elk)
    args = query(
        source_ip="203.0.113.0/24",
        destination_ip="2001:db8::1",
        user_name="u",
        host_name="h",
        url_path="/",
    )
    assert parse(call(c, "query_siem", args))["hits"] == []


def test_target_filters_and_fields_are_known_constants() -> None:
    assert TARGET_NAMES == ("alerts", "web_access", "cloudtrail", "evidence")
    for name in TARGET_NAMES:
        assert set(TARGET_FILTERS[name]) <= set(FILTERS)
    assert FILTERS["rule_name"] == "kibana.alert.rule.name"
    assert FILTERS["alert_severity"] == "kibana.alert.severity"
    assert "kibana.alert.rule.name" in TARGET_FIELDS["alerts"]


def test_descriptions_list_filters_per_target_and_field_schema() -> None:
    specs = {s.name: s for s in siem_tools()}
    for spec in specs.values():
        for name in TARGET_NAMES:
            assert name in spec.description
            for arg in TARGET_FILTERS[name]:
                assert arg in spec.description
        assert "ecs" in spec.description.lower()
        assert "kibana.alert.*" in spec.description
        assert spec.result_kind == "aggregate"
        assert spec.id_fields == ()
    target = next(a for a in specs["query_siem"].args if a.name == "target")
    assert target.enum == TARGET_NAMES and target.required


# 설정 검사


@pytest.mark.parametrize(
    "targets",
    [
        [*TARGETS, {"name": "firewall", "index": "logs-fw-*", "time_field": "@timestamp"}],
        [TARGETS[0], TARGETS[0]],
        [{"index": "logs-*", "time_field": "@timestamp"}],
        "alerts",
    ],
)
def test_bad_target_config_is_provider_error(env: None, targets: Any) -> None:
    fake = FakeElk()
    cfg = config(siem={**SIEM, "targets": targets})
    with pytest.raises(ToolConfigError):
        registry(fake).session(stage="l1", config=cfg, recorder=new_recorder())
    result = run_task(
        make_task(),
        model=FakeModel({"steps": [{"final": {}}]}),
        model_name="fake-model",
        log_sink=MemoryLogSink(),
        config=cfg,
        registry=registry(fake),
        sleep=no_sleep,
    )
    assert result.failure == "provider_error"
    assert fake.requests == []


def test_config_is_not_checked_when_tools_are_not_allowed(env: None) -> None:
    cfg = config(siem={**SIEM, "targets": [{"name": "firewall"}]})
    cfg["tools"]["allowed"] = {"l1": []}
    Caller(registry(FakeElk()), cfg)  # 허용되지 않은 도구의 설정은 보지 않는다


# 오류: TOOL_ERROR 문구, details.failure, details.reason


def _raise(exc: Exception):
    def answer(request: httpx.Request) -> httpx.Response:
        raise exc

    return answer


ERRORS = [
    (
        "connect_error",
        _raise(httpx.ConnectError("connect to elk.example.com failed")),
        "unavailable",
        "network",
    ),
    ("read_error", _raise(httpx.ReadError("reset by elk.example.com")), "unavailable", "network"),
    ("connect_timeout", _raise(httpx.ConnectTimeout("elk.example.com")), "timeout", None),
    ("read_timeout", _raise(httpx.ReadTimeout("elk.example.com")), "timeout", None),
    ("401", status(401, "error_401.json"), "failed", "auth"),
    ("403", status(403, "error_401.json"), "failed", "auth"),
    ("500", status(500, "error_500.json"), "failed", "http_status"),
    ("404", status(404, "error_500.json"), "failed", "http_status"),
    (
        "redirect",
        status(302, headers={"location": "https://elk-internal.example.com/x/_search"}),
        "failed",
        "http_status",
    ),
    ("malformed", ok("malformed.json"), "failed", "response_shape"),
    (
        "not_json",
        httpx.Response(200, content=b"<html>elk-internal</html>"),
        "failed",
        "response_shape",
    ),
    ("not_object", httpx.Response(200, json=["x"]), "failed", "response_shape"),
]


@pytest.mark.parametrize(
    ("answer", "code", "reason"),
    [e[1:] for e in ERRORS],
    ids=[e[0] for e in ERRORS],
)
def test_errors_follow_the_plan_table(
    elk: FakeElk, answer: Any, code: str, reason: str | None
) -> None:
    elk.add(answer)
    c = caller(elk)
    out = call(c, "query_siem", query(source_ip="203.0.113.10"))
    assert out == tool_error_text("query_siem", code)
    row = c.rows[0]
    assert row["outcome"] == "error"
    assert row["details"]["failure"] == code
    assert row["details"].get("reason") == reason
    assert len(elk.requests) == 1  # 리다이렉트를 따라가지 않는다
    assert leaked(out + json.dumps(c.rows, ensure_ascii=False)) == []
    assert not c.session.evidence_ids


def test_count_errors_use_the_same_table(elk: FakeElk) -> None:
    elk.add(status(403, "error_401.json"), ok("search_web_access.json"))
    c = caller(elk)
    assert call(c, "count_siem", count()) == tool_error_text("count_siem", "failed")
    assert failure(c.rows[0]) == {"failure": "failed", "reason": "auth"}
    # aggregations가 없는 응답은 모양 이상이다
    assert call(c, "count_siem", count()) == tool_error_text("count_siem", "failed")
    assert c.rows[1]["details"]["reason"] == "response_shape"


def test_response_over_max_bytes_is_cut(elk: FakeElk) -> None:
    elk.add(ok("search_large.json"))
    c = caller(elk, config(siem={**SIEM, "max_bytes": 4_096}))
    out = call(c, "query_siem", query())
    assert out == tool_error_text("query_siem", "failed")
    assert failure(c.rows[0]) == {"failure": "failed", "reason": "too_large"}


def test_deadline_is_checked_while_streaming(elk: FakeElk) -> None:
    body = json.dumps({"hits": {"total": {"value": 0, "relation": "eq"}, "hits": []}}).encode()
    elk.add(chunks([body[:10], body[10:20], body[20:]]))
    ticks = itertools.count(0, 10)  # 부를 때마다 10초씩 간다. 실제로 기다리지 않는다
    c = caller(elk, clock=lambda: next(ticks))
    out = call(c, "query_siem", query())
    assert out == tool_error_text("query_siem", "timeout")
    assert failure(c.rows[0]) == {"failure": "timeout"}


def test_within_deadline_is_ok(elk: FakeElk) -> None:
    body = json.dumps({"hits": {"total": {"value": 0, "relation": "eq"}, "hits": []}}).encode()
    elk.add(chunks([body[:10], body[10:]]))
    c = caller(elk, clock=lambda: 0.0)
    assert parse(call(c, "query_siem", query()))["hits"] == []


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        ("ELK_URL", None),
        ("ELK_API_KEY", None),
        ("ELK_URL", ""),
        ("ELK_URL", "https://reader:fake-pass-8888@elk.example.com:9200"),
        ("ELK_URL", "ftp://elk.example.com"),
        ("ELK_URL", "elk.example.com:9200"),
    ],
)
def test_missing_or_bad_environment_is_unavailable(
    elk: FakeElk, monkeypatch: pytest.MonkeyPatch, variable: str, value: str | None
) -> None:
    if value is None:
        monkeypatch.delenv(variable, raising=False)
    else:
        monkeypatch.setenv(variable, value)
    c = caller(elk)
    out = call(c, "query_siem", query())
    assert out == tool_error_text("query_siem", "unavailable")
    assert failure(c.rows[0]) == {"failure": "unavailable", "reason": "config"}
    assert elk.requests == []
    assert "fake-pass-8888" not in json.dumps(c.rows) + out


@pytest.mark.parametrize(
    "change",
    [
        {"targets": [{**TARGETS[1], "index": "logs-web/../_all"}]},
        {"targets": [{**TARGETS[1], "index": "_all"}]},
        {"targets": [{**TARGETS[1], "index": "logs-web?pretty"}]},
        {"targets": [{**TARGETS[1], "time_field": '@timestamp"}'}]},
        {"targets": [{**TARGETS[1], "index": ""}]},
        {"deadline_seconds": 0},
        {"max_bytes": "5MB"},
        {"connect_timeout_seconds": True},
    ],
)
def test_bad_settings_fail_with_config_reason(elk: FakeElk, change: dict[str, Any]) -> None:
    c = caller(elk, config(siem={**SIEM, **change}))
    out = call(c, "query_siem", query())
    assert out == tool_error_text("query_siem", "failed")
    assert failure(c.rows[0]) == {"failure": "failed", "reason": "config"}
    assert elk.requests == []


# CA 인증서 경로 [tools.siem] ca_cert_path(#264). 샘플은 tests/fixtures/tls/의 테스트용 공개 CA다


TLS = Path(__file__).parent / "fixtures" / "tls"


def spy_verify(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """도구가 httpx.Client에 넘긴 verify 값을 모은다. 요청은 transport(FakeElk)로 그대로 간다."""
    seen: list[Any] = []
    real = httpx.Client

    def spy(*args: Any, **kwargs: Any) -> httpx.Client:
        seen.append(kwargs.get("verify"))
        return real(*args, **kwargs)

    monkeypatch.setattr("soc.tools.siem.httpx.Client", spy)
    return seen


def test_ca_cert_path_becomes_ssl_context(elk: FakeElk, monkeypatch: pytest.MonkeyPatch) -> None:
    import ssl

    seen = spy_verify(monkeypatch)
    elk.add(ok("search_web_access.json"), ok("search_web_access.json"))
    call(
        caller(elk, config(siem={**SIEM, "ca_cert_path": str(TLS / "ca.pem")})),
        "query_siem",
        query(),
    )
    call(caller(elk, config(siem={**SIEM, "ca_cert_path": ""})), "query_siem", query())
    assert isinstance(seen[0], ssl.SSLContext)
    subjects = [dict(item[0] for item in c["subject"]) for c in seen[0].get_ca_certs()]
    assert {"commonName": "0-Ticket test CA"} in subjects
    assert seen[1] is True
    assert len(elk.requests) == 2


def test_missing_ca_cert_path_key_keeps_default_verification(
    elk: FakeElk, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen = spy_verify(monkeypatch)
    elk.add(ok("search_web_access.json"))
    call(caller(elk), "query_siem", query())
    assert seen == [True]


@pytest.mark.parametrize(
    "value", [str(TLS / "missing.pem"), str(TLS / "not_a_cert.pem"), str(TLS), 1, None]
)
def test_bad_ca_cert_path_fails_with_config_reason(elk: FakeElk, value: Any) -> None:
    c = caller(elk, config(siem={**SIEM, "ca_cert_path": value}))
    out = call(c, "query_siem", query())
    assert out == tool_error_text("query_siem", "failed")
    assert failure(c.rows[0]) == {"failure": "failed", "reason": "config"}
    assert elk.requests == []
    assert str(TLS) not in json.dumps(c.rows) + out


def test_two_failures_block_the_tool(elk: FakeElk) -> None:
    elk.add(status(500, "error_500.json"), status(500, "error_500.json"))
    c = caller(elk)
    call(c, "query_siem", query())
    call(c, "query_siem", query())
    out = call(c, "query_siem", query())
    assert out == tool_error_text("query_siem", "not_allowed")
    assert c.rows[2]["details"]["blocked"] is True
    assert len(elk.requests) == 2


# 실행 전체: 근거 장부, Agent Log, detail


def verdict(*ids: str) -> dict[str, Any]:
    return {"decision": "benign", "confidence": 0.9, "reason": "테스트", "evidence_ids": list(ids)}


def run(fake: FakeElk, steps: list[dict[str, Any]], cfg: dict[str, Any] | None = None):
    model = FakeModel({"steps": steps})
    sink = MemoryLogSink()
    result = run_task(
        make_task(),
        model=model,
        model_name="fake-model",
        log_sink=sink,
        config=cfg or config(),
        registry=registry(fake),
        sleep=no_sleep,
    )
    return result, model, sink


def siem_call(arguments: dict[str, Any], name: str = "query_siem") -> dict[str, Any]:
    return {"tool_call": {"name": name, "arguments": arguments}}


def test_verdict_citing_the_call_id_passes(elk: FakeElk) -> None:
    elk.add(ok("search_web_access.json"))

    def cite(outputs: list[str]) -> dict[str, Any]:
        return verdict(ALERT_ID, parse(outputs[0])["call_id"])

    result, model, sink = run(elk, [siem_call(query(source_ip="203.0.113.10")), {"final_fn": cite}])
    assert result.ok is True, result.detail
    out = parse(tool_outputs(model.calls[-1]["input"])[0])
    row = next(r for r in sink.rows if r["kind"] == "tool")
    assert out["call_id"] == row["id"]
    assert out["call_id"] in result.cited_evidence_ids
    assert row["output"]["hits"] == out["hits"]


@pytest.mark.parametrize(
    "cited",
    [
        ".ds-logs-nginx.access-default-2026.11.04-000001/web-doc-0001",  # siem_ref
        "web-doc-0001",
    ],
)
def test_citing_siem_ref_is_rejected(elk: FakeElk, cited: str) -> None:
    # siem_ref는 근거 ID 모양(alt_·evt_·agl_)이 아니라 Verdict 계약 검사에서 먼저 막힌다.
    # 재요청에도 같은 것을 인용하면 format_error로 끝난다(장부 검사까지 가지 않는다).
    elk.add(ok("search_web_access.json"))
    bad = {"final": verdict(ALERT_ID, cited)}
    result, _, _ = run(elk, [siem_call(query()), bad, bad])
    assert result.ok is False
    assert result.failure == "format_error"


def test_citing_alert_id_in_result_body_is_evidence_id_error(elk: FakeElk) -> None:
    elk.add(ok("search_web_access.json"))
    cited = "alt_01a19f93-1150-7000-8000-00000000beef"  # 결과 본문 속 alt_ 모양 문자열
    result, _, _ = run(elk, [siem_call(query()), {"final": verdict(ALERT_ID, cited)}])
    assert result.failure == "evidence_id_error"


def test_auth_failure_hides_everything_in_a_full_run(elk: FakeElk) -> None:
    elk.add(status(401, "error_401.json"))

    def cite(outputs: list[str]) -> dict[str, Any]:
        assert outputs[0] == tool_error_text("query_siem", "failed")
        return verdict(ALERT_ID)

    result, model, sink = run(elk, [siem_call(query()), {"final_fn": cite}])
    assert result.ok is True, result.detail
    assert result.usage["tool_errors"] == 1
    row = next(r for r in sink.rows if r["kind"] == "tool")
    assert failure(row) == {"failure": "failed", "reason": "auth"}
    model_inputs = json.dumps([c["input"] for c in model.calls], ensure_ascii=False, default=str)
    text = model_inputs + json.dumps(sink.rows, ensure_ascii=False) + str(result.detail)
    assert leaked(text) == []


def test_api_key_and_url_are_redacted_from_agent_log(elk: FakeElk) -> None:
    # ES가 키와 주소를 결과 본문에 되돌려 보내도 Agent Log에서는 가려진다(*_env 가림, #209)
    echo = {
        "hits": {
            "total": {"value": 1, "relation": "eq"},
            "hits": [
                {
                    "_index": "logs-nginx.access-x",
                    "_id": "d1",
                    "_source": {"user_agent": {"original": f"{ELK_KEY} {ELK_URL}"}},
                }
            ],
        }
    }
    elk.add(httpx.Response(200, json=echo))
    result, _, sink = run(elk, [siem_call(query()), {"final": verdict(ALERT_ID)}])
    assert result.ok is True, result.detail
    text = json.dumps(sink.rows, ensure_ascii=False)
    assert ELK_KEY not in text
    assert ELK_URL not in text


# 기본 설정·운영 레지스트리·마커


def test_default_config_has_siem_settings_without_secrets(default_config_dir: Path) -> None:
    tools = load_config(default_config_dir)["tools"]
    siem = tools["siem"]
    assert siem["url_env"] == "ELK_URL"
    assert siem["api_key_env"] == "ELK_API_KEY"
    assert siem["connect_timeout_seconds"] == 5
    assert siem["read_timeout_seconds"] == 10
    assert siem["deadline_seconds"] == 15
    assert siem["max_bytes"] == 5_242_880
    assert siem["ca_cert_path"] == ""
    assert [t["name"] for t in siem["targets"]] == list(TARGET_NAMES)
    by_name = {t["name"]: t for t in siem["targets"]}
    assert by_name["alerts"]["index"] == ".alerts-security.alerts-default"
    assert by_name["web_access"]["index"] == WEB_INDEX
    assert by_name["cloudtrail"]["index"] == "logs-aws.cloudtrail-*"
    assert all(t["time_field"] == "@timestamp" for t in siem["targets"])
    allowed = tools["allowed"]
    # 근거를 발급하는 태스크만 심을 본다. l1은 건수 집계를 쓰지 않는다
    for task in ("l1_alert_triage", "l1_ticket_judgment"):
        assert "query_siem" in allowed[task] and "count_siem" not in allowed[task], task
    for task in ("l2_investigate", "l3_hypothesize", "l3_verify"):
        assert {"query_siem", "count_siem"} <= set(allowed[task]), task
    # 인용해도 발급할 다음 태스크가 없는 두 태스크다(D-082)
    for task in ("l2_classify", "l2_report"):
        assert not {"query_siem", "count_siem"} & set(allowed[task]), task


def test_default_config_passes_the_config_check(env: None) -> None:
    cfg = load_config(REPO / "config")
    full = {**CONFIG, "tools": cfg["tools"]}
    for stage in ("l1", "l2", "l3"):
        Caller(default_registry(), full, stage=stage)


def test_env_example_has_names_only() -> None:
    lines = (REPO / ".env.example").read_text(encoding="utf-8").splitlines()
    for name in ("ELK_URL", "ELK_API_KEY"):
        found = [line for line in lines if line.lstrip("# ").startswith(f"{name}=")]
        assert len(found) == 1, name
        assert found[0].rstrip().endswith("=")


def test_elk_marker_is_excluded_by_default() -> None:
    pytest_config = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    options = pytest_config["tool"]["pytest"]["ini_options"]
    assert any(m.startswith("elk:") for m in options["markers"])
    assert "not elk" in options["addopts"]


# siem_ref → (_index, _id) 맵 (#382)
#
# 워커가 원문 한 건을 가져오려면 인덱스와 문서 ID가 필요한데, siem_ref 저장 키는 되돌릴 수 없다
# (soc.ids.siem_ref_key: "키는 / 로 나누어 _index와 _id로 되돌리지 않는다"). 그래서 query_siem이
# 모델에게 보인 히트의 (_index, _id)를 도구 세션이 들고 있는다.
# 모델에게는 인덱스 이름이 가지 않는다.


def siem_hit(index: str, doc_id: str, **source: Any) -> dict[str, Any]:
    return {"_index": index, "_id": doc_id, "_source": {"@timestamp": START + 1000, **source}}


def hits_response(*hits: dict[str, Any]) -> httpx.Response:
    total = {"value": len(hits), "relation": "eq"}
    return httpx.Response(200, json={"hits": {"total": total, "hits": list(hits)}})


def test_shown_hits_land_in_the_session_siem_refs_map(elk: FakeElk) -> None:
    index = ".ds-logs-nginx.access-default-2026.11.04-000001"
    elk.add(hits_response(siem_hit(index, "aaa1"), siem_hit(index, "bbb2")))
    c = caller(elk)
    body = parse(call(c, "query_siem", query()))

    assert [h["siem_ref"] for h in body["hits"]] == [
        siem_ref_key(f"{index}/aaa1"),
        siem_ref_key(f"{index}/bbb2"),
    ]
    assert c.session.siem_refs == {
        siem_ref_key(f"{index}/aaa1"): (index, "aaa1"),
        siem_ref_key(f"{index}/bbb2"): (index, "bbb2"),
    }


def test_map_value_keeps_the_original_id_not_the_stored_key(elk: FakeElk) -> None:
    # 저장 키는 JSON 이스케이프된 값이라 그대로 URL 경로에 쓰면 다른 문서를 가리킨다.
    # 맵의 값은 ELK가 준 원래 _id여야 한다.
    index = ".ds-logs-web-default-2026.11.04-000001"
    doc_id = 'q"b\\s\x01z한글'
    elk.add(hits_response(siem_hit(index, doc_id)))
    c = caller(elk)
    body = parse(call(c, "query_siem", query()))

    ref = body["hits"][0]["siem_ref"]
    assert ref == siem_ref_key(f"{index}/{doc_id}")
    assert ref != f"{index}/{doc_id}"  # 이스케이프가 실제로 일어났다
    assert c.session.siem_refs[ref] == (index, doc_id)


def test_hits_dropped_to_fit_are_not_in_the_map(elk: FakeElk) -> None:
    # 뒤에서 빠진 히트는 모델이 보지 못했으므로 인용할 수 없고, 맵에도 없어야 한다.
    index = ".ds-logs-web-default-2026.11.04-000001"
    big = "x" * 400
    elk.add(hits_response(*[siem_hit(index, f"id{n}", **{"url.path": big}) for n in range(8)]))
    c = caller(elk, config(chars=900))
    body = parse(call(c, "query_siem", query()))

    assert body["omitted"] > 0
    shown = {h["siem_ref"] for h in body["hits"]}
    assert shown
    assert set(c.session.siem_refs) == shown


def test_a_failed_call_leaves_the_map_untouched(elk: FakeElk) -> None:
    index = ".ds-logs-web-default-2026.11.04-000001"
    elk.add(hits_response(siem_hit(index, "kept")))
    elk.add(status(500))
    c = caller(elk)
    call(c, "query_siem", query())
    before = dict(c.session.siem_refs)
    call(c, "query_siem", query(source_ip="203.0.113.9"))

    assert c.session.siem_refs == before == {siem_ref_key(f"{index}/kept"): (index, "kept")}


def test_count_siem_adds_nothing_to_the_map(elk: FakeElk) -> None:
    elk.add(ok("terms.json"))
    c = caller(elk)
    call(c, "count_siem", count())

    assert c.session.siem_refs == {}


# 원문 한 건 가져오기 (#382)
#
# 도구가 아니라 근거 발급 워커가 부른다. GET /<index>/_doc/<id> 하나이고, 접속·마감·상한 규칙은
# query_siem과 같은 함수를 쓴다. 돌려주는 모양은 수집이 raw_records.original_text에 넣는 것과 같은
# 세 칸(_index, _id, _source)이다.


def siem_config() -> dict[str, Any]:
    return config()["tools"]["siem"]


def fetch(fake: FakeElk, index: str, doc_id: str, clock: Any = None) -> dict[str, Any]:
    return siem_mod.fetch_document(
        siem_config(),
        index,
        doc_id,
        transport=fake.transport(),
        clock=clock or itertools.count(0.0, 0.1).__next__,
    )


def doc_response(index: str, doc_id: str, source: dict[str, Any]) -> httpx.Response:
    return httpx.Response(
        200,
        json={"_index": index, "_id": doc_id, "_version": 3, "found": True, "_source": source},
    )


def test_fetch_returns_the_three_columns_ingest_stores(elk: FakeElk) -> None:
    index = ".ds-logs-nginx.access-default-2026.11.04-000001"
    source = {"@timestamp": "2026-11-04T00:00:01Z", "event": {"module": "suricata"}}
    elk.add(doc_response(index, "abc1", source))

    got = fetch(elk, index, "abc1")

    assert got == {"_index": index, "_id": "abc1", "_source": source}
    assert elk.requests[-1].method == "GET"


def test_fetch_percent_encodes_an_odd_doc_id(elk: FakeElk) -> None:
    # _id를 경로에 그대로 넣으면 다른 문서를 가리키거나 경로가 깨진다.
    index = ".ds-logs-web-default-2026.11.04-000001"
    doc_id = 'q"b\\s\x01z한글'
    elk.add(doc_response(index, doc_id, {"a": 1}))

    got = fetch(elk, index, doc_id)

    raw_path = elk.requests[-1].url.raw_path.decode("ascii")
    assert raw_path.startswith(f"/{index}/_doc/")
    assert "/" not in raw_path[len(f"/{index}/_doc/") :]
    assert elk.requests[-1].url.path == f"/{index}/_doc/{doc_id}"
    assert got["_id"] == doc_id


def test_fetch_does_not_truncate_the_source(elk: FakeElk) -> None:
    # 불변 사본이 목적이므로 도구의 자르기(FIELD_MAX_CHARS, SEARCH_MAX)가 걸리지 않아야 한다.
    index = ".ds-logs-web-default-2026.11.04-000001"
    long_value = "y" * (FIELD_MAX_CHARS * 5)
    elk.add(doc_response(index, "big", {"message": long_value}))

    got = fetch(elk, index, "big")

    assert got["_source"]["message"] == long_value
    assert CUT_MARK not in got["_source"]["message"]


def test_fetch_of_a_missing_document_is_an_error(elk: FakeElk) -> None:
    index = ".ds-logs-web-default-2026.11.04-000001"
    elk.add(httpx.Response(404, json={"_index": index, "_id": "gone", "found": False}))

    with pytest.raises(siem_mod.ToolError) as exc:
        fetch(elk, index, "gone")
    assert exc.value.code == "failed"


def test_fetch_with_found_false_is_an_error(elk: FakeElk) -> None:
    index = ".ds-logs-web-default-2026.11.04-000001"
    elk.add(httpx.Response(200, json={"_index": index, "_id": "gone", "found": False}))

    with pytest.raises(siem_mod.ToolError):
        fetch(elk, index, "gone")


def test_fetch_auth_failure_is_reported_as_auth(elk: FakeElk) -> None:
    elk.add(status(401, "error_401.json"))

    with pytest.raises(siem_mod.ToolError) as exc:
        fetch(elk, ".ds-x-000001", "a")
    assert exc.value.reason == "auth"


def test_fetch_stops_over_the_size_cap(elk: FakeElk) -> None:
    cfg = {**siem_config(), "max_bytes": 64}
    elk.add(doc_response(".ds-x-000001", "a", {"m": "z" * 500}))

    with pytest.raises(siem_mod.ToolError) as exc:
        siem_mod.fetch_document(
            cfg,
            ".ds-x-000001",
            "a",
            transport=elk.transport(),
            clock=itertools.count(0.0, 0.1).__next__,
        )
    assert exc.value.reason == "too_large"


def test_fetch_error_text_leaks_no_address_or_key(elk: FakeElk) -> None:
    elk.add(status(500, "error_500.json"))

    with pytest.raises(siem_mod.ToolError) as exc:
        fetch(elk, ".ds-x-000001", "a")
    assert leaked(f"{exc.value.code} {exc.value.reason}") == []


def test_fetch_rejects_a_pattern_or_multi_index(elk: FakeElk) -> None:
    # 맵의 값은 히트 하나의 _index라 늘 구체 이름이다. 패턴을 받으면 엉뚱한 문서를 가리킨다.
    for index in ("logs-nginx.access-*", "logs-a-000001,logs-b-000001"):
        with pytest.raises(siem_mod.ToolError) as exc:
            siem_mod.fetch_document(siem_config(), index, "a", transport=elk.transport())
        assert exc.value.code == "invalid_argument", index
    assert elk.requests == []


# 소스 구분 없는 대상 (#382)
#
# 이벤트 정규화를 없애면서 수리카타처럼 매핑표가 없는 소스도 근거로 써야 한다. 대상 하나에 ECS
# 공통 필터·반환 필드만 두고 event.module로 좁힌다. 안 좁히면 여러 소스가 함께 걸린다.

EVIDENCE = "evidence"


def evidence_query(**kwargs: Any) -> dict[str, Any]:
    return {"target": EVIDENCE, "start_ms": START, "end_ms": END, **kwargs}


def test_evidence_target_exists_with_ecs_common_filters_only() -> None:
    assert EVIDENCE in TARGET_NAMES
    assert set(TARGET_FILTERS[EVIDENCE]) == {
        "source_ip",
        "destination_ip",
        "user_name",
        "host_name",
        "url_path",
        "http_method",
        "status_code",
        "event_module",
        "event_dataset",
    }
    # 소스 고유 필드는 쓰지 않는다. 알럿 전용 필터도 없다
    assert "rule_name" not in TARGET_FILTERS[EVIDENCE]
    assert "alert_severity" not in TARGET_FILTERS[EVIDENCE]
    assert "cloud_account_id" not in TARGET_FILTERS[EVIDENCE]


def test_evidence_target_returns_ecs_common_fields() -> None:
    fields = set(TARGET_FIELDS[EVIDENCE])
    assert {"event.module", "event.dataset", "source.ip", "url.path"} <= fields
    assert not any(f.startswith("kibana.") for f in fields)


def test_event_module_filter_narrows_to_one_source(elk: FakeElk) -> None:
    elk.add(ok("empty.json"))
    c = caller(elk)
    call(c, "query_siem", evidence_query(event_module="suricata"))

    body = elk.bodies()[-1]
    terms = [f for f in body["query"]["bool"]["filter"] if "term" in f]
    assert {"term": {"event.module": "suricata"}} in terms


def test_evidence_target_without_a_module_filter_catches_every_source(elk: FakeElk) -> None:
    index = ".ds-filebeat-9.5.0-2026.11.04-000001"
    hits = [
        siem_hit(index, f"id{n}", **{"event.module": module})
        for n, module in enumerate(("suricata", "modsecurity", "nginx"))
    ]
    elk.add(hits_response(*hits))
    c = caller(elk)
    body = parse(call(c, "query_siem", evidence_query()))

    modules = [h["fields"]["event.module"] for h in body["hits"]]
    assert modules == ["suricata", "modsecurity", "nginx"]
    # 모델에게 보인 히트는 모두 원문을 가져올 수 있다
    assert set(c.session.siem_refs) == {h["siem_ref"] for h in body["hits"]}


def test_alert_only_filters_are_rejected_on_the_evidence_target(elk: FakeElk) -> None:
    c = caller(elk)
    text = call(c, "query_siem", evidence_query(rule_name="IRLAB"))

    assert text.startswith("TOOL_ERROR tool=query_siem code=invalid_argument")
    assert elk.requests == []


def test_default_config_has_the_evidence_target(env: None) -> None:
    targets = load_config(REPO / "config")["tools"]["siem"]["targets"]
    by_name = {t["name"]: t for t in targets}
    assert EVIDENCE in by_name
    index = by_name[EVIDENCE]["index"]
    # 소스를 가리지 않도록 넓게 두고 실제 값은 config/local.toml에서 좁힌다
    assert "filebeat" in index and "logs-" in index
    assert by_name[EVIDENCE]["time_field"] == "@timestamp"
