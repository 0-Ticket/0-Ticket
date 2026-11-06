"""SIEM 조회 도구(#212): query_siem, count_siem.

수집(#218)과 같은 ELK에 [tools.siem]의 url_env·api_key_env가 가리키는 환경변수
(ELK_URL·ELK_API_KEY)로 접속한다. SIEM 연결·프로필(D-021)이 생기면 그것으로 바꾼다.
키는 읽기 전용 API 키다(D-010).

- 부르는 API는 POST /<대상 index>/_search 하나다. PIT·scroll·쓰기 API는 부르지 않는다.
- 모델은 쿼리를 쓰지 않는다. 대상 이름·필터 인자만 고르고, 도구가 bool.filter(range + term) dict를
  만든다. 필드 이름은 아래 상수에서만 고르고, 모델이 준 값은 term 값 자리에만 들어간다.
- 대상 이름과 대상별 필터·반환 필드는 코드 상수다(도구 설명과 enum이 정적이라). 설정
  [[tools.siem.targets]]는 이름에 index·time_field만 붙인다.
- HTTP는 httpx(D-039). 리다이렉트는 따라가지 않고, 요청 단위 timeout과 별도로 전체 마감 시간을 본다.
  응답은 스트리밍으로 받으며 압축을 푼 바이트가 상한을 넘으면 끊는다.
- 결과는 ELK 원본 필드(ECS)다. OCSF로 정규화하지 않는다. result_kind는 aggregate다(핸들러가 모양과
  한도를 정하고, 인용은 call_id만). 응답 본문·주소·키·쿼리는 오류 문구와 details에 넣지 않는다.
- 핸들러는 동기 httpx로 부른다. DB 도구처럼 이벤트 루프를 최대 deadline_seconds까지 막는다.
"""

import ipaddress
import json
import os
import re
import ssl
import time
from collections.abc import Callable, Mapping
from typing import Any

import httpx

from soc.tools.internal import SORT_ARG, TIME_RANGE_ARGS, check_time_range
from soc.tools.registry import CUT_MARK, Arg, CallContext, ToolConfigError, ToolError, ToolSpec

TARGET_NAMES = ("alerts", "web_access", "cloudtrail")
# 필터 인자 이름 → ELK 필드. keyword·숫자·ip 타입 필드만 둔다(term·terms가 그대로 맞는다).
FILTERS: dict[str, str] = {
    "source_ip": "source.ip",
    "destination_ip": "destination.ip",
    "user_name": "user.name",
    "host_name": "host.name",
    "url_path": "url.path",
    "http_method": "http.request.method",
    "status_code": "http.response.status_code",
    "event_action": "event.action",
    "cloud_account_id": "cloud.account.id",
    # Elastic Security 알럿 필드(ECS 아님). 실제 매핑 확정은 #208
    "rule_name": "kibana.alert.rule.name",
    "alert_severity": "kibana.alert.severity",
}
IP_FILTERS = ("source_ip", "destination_ip")
TARGET_FILTERS: dict[str, tuple[str, ...]] = {
    "alerts": (
        "rule_name",
        "alert_severity",
        "source_ip",
        "destination_ip",
        "user_name",
        "host_name",
    ),
    "web_access": (
        "source_ip",
        "destination_ip",
        "url_path",
        "http_method",
        "status_code",
        "user_name",
        "host_name",
    ),
    "cloudtrail": ("source_ip", "user_name", "event_action", "cloud_account_id"),
}
# query_siem이 돌려주는 _source 필드(시각 필드는 설정의 time_field를 앞에 더한다)
TARGET_FIELDS: dict[str, tuple[str, ...]] = {
    "alerts": (
        "kibana.alert.rule.name",
        "kibana.alert.severity",
        "kibana.alert.risk_score",
        "kibana.alert.reason",
        "kibana.alert.workflow_status",
        "source.ip",
        "destination.ip",
        "user.name",
        "host.name",
        "event.action",
    ),
    "web_access": (
        "source.ip",
        "destination.ip",
        "url.path",
        "url.query",
        "http.request.method",
        "http.response.status_code",
        "http.response.body.bytes",
        "user_agent.original",
        "user.name",
        "host.name",
    ),
    "cloudtrail": (
        "event.action",
        "event.provider",
        "event.outcome",
        "source.ip",
        "user.name",
        "user_agent.original",
        "cloud.account.id",
        "cloud.region",
    ),
}
MAX_FILTERS = 5
TOP_N = 10
FIELD_MAX_CHARS = 300  # query_siem 결과의 문자열 값 하나
VALUE_MAX_CHARS = 120  # count_siem 결과의 값 하나(#211 summarize_http_flow와 같다)
TRACK_TOTAL_HITS = 10_000
SOURCE_NAME = "siem"
SCHEMA_NAME = "ecs"
SEARCH_MAX = 200

# 조회 대상 index는 URL 경로(/<index>/_search)에 들어간다. 경로·질의를 바꾸는 /, ?, #, 공백을
# 받지 않고 _로 시작하는 이름(_all 등 API 이름)도 받지 않는다(#218과 같은 규칙). 여러 대상은 쉼표.
_INDEX = re.compile(r"[A-Za-z0-9.*,:+-][A-Za-z0-9._*,:+-]*")
_FIELD = re.compile(r"[A-Za-z0-9@_][A-Za-z0-9@._-]*")
_TIMEOUT_KEYS = ("connect_timeout_seconds", "read_timeout_seconds", "deadline_seconds")


def _filter_args() -> tuple[Arg, ...]:
    args = []
    for name, field in FILTERS.items():
        if name in IP_FILTERS:
            arg = Arg(
                name,
                "string",
                min_length=1,
                max_length=64,
                pattern=r"[0-9A-Fa-f:./]+",
                description=f"{field}: IP 주소 또는 CIDR(정확히 일치)",
            )
        elif name == "status_code":
            arg = Arg(
                name, "integer", minimum=100, maximum=599, description=f"{field}: HTTP 응답 코드"
            )
        elif name == "http_method":
            arg = Arg(
                name,
                "string",
                min_length=1,
                max_length=16,
                pattern="[A-Za-z]+",
                description=f"{field}: HTTP 메서드(정확히 일치, 예: GET)",
            )
        elif name == "alert_severity":
            arg = Arg(
                name,
                "string",
                enum=("low", "medium", "high", "critical"),
                description=f"{field}: 알럿 심각도",
            )
        else:
            arg = Arg(
                name,
                "string",
                min_length=1,
                max_length=SEARCH_MAX,
                description=f"{field}: 정확히 일치",
            )
        args.append(arg)
    return tuple(args)


TARGET_ARG = Arg(
    "target",
    "string",
    required=True,
    enum=TARGET_NAMES,
    description="조회 대상 이름. 대상마다 쓸 수 있는 필터가 다르다(도구 설명 참고)",
)
FILTER_ARGS = _filter_args()
FIELD_ARG = Arg(
    "field",
    "string",
    required=True,
    enum=tuple(FILTERS),
    description="건수를 셀 필드(필터 인자 이름). 고른 대상에서 쓸 수 있는 것만",
)


def _target_lines() -> str:
    return "\n".join(f"- {name}: 필터 {', '.join(TARGET_FILTERS[name])}" for name in TARGET_NAMES)


_COMMON_DESCRIPTION = (
    "결과는 SIEM(ELK)의 원본 필드 이름(ECS)이다. OCSF로 정규화하지 않았다. "
    "kibana.alert.*는 ECS가 아니라 Elastic Security 필드다. "
    "필터는 한 번에 최대 5개이고 모두 정확히 일치(AND)다. 시간은 start_ms 이상 end_ms 미만이다. "
    "결과는 이 호출의 call_id로만 인용한다(siem_ref는 인용할 수 없다).\n"
    "대상과 쓸 수 있는 필터:\n"
)


# 설정


def _check_config(tools_config: Mapping[str, Any]) -> None:
    """[[tools.siem.targets]]의 이름을 검사한다. 틀리면 실행이 provider_error로 끝난다.

    index·time_field 형식과 접속 설정은 호출할 때 검사한다(failed, reason=config).
    """
    siem = tools_config.get("siem", {})
    if not isinstance(siem, Mapping):
        raise ToolConfigError("[tools.siem]이 표가 아니다")
    targets = siem.get("targets", [])
    if not isinstance(targets, list):
        raise ToolConfigError("[[tools.siem.targets]]가 목록이 아니다")
    names = []
    for target in targets:
        if not isinstance(target, Mapping) or target.get("name") not in TARGET_NAMES:
            raise ToolConfigError("[[tools.siem.targets]]에 코드에 없는 대상 이름이 있다")
        names.append(target["name"])
    if len(names) != len(set(names)):
        raise ToolConfigError("[[tools.siem.targets]]에 같은 이름이 두 번 있다")


def _configured_targets(tools_config: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    siem = tools_config.get("siem", {})
    targets = siem.get("targets", []) if isinstance(siem, Mapping) else []
    return {t["name"]: t for t in targets if isinstance(t, Mapping) and "name" in t}


def _target(args: Mapping[str, Any], tools_config: Mapping[str, Any]) -> tuple[str, str]:
    """(index, time_field). 형식이 틀리면 failed(config)."""
    target = _configured_targets(tools_config)[args["target"]]
    index, time_field = target.get("index"), target.get("time_field")
    if not isinstance(index, str) or not _INDEX.fullmatch(index):
        raise ToolError("failed", reason="config")
    if not isinstance(time_field, str) or not _FIELD.fullmatch(time_field):
        raise ToolError("failed", reason="config")
    return index, time_field


def _positive(siem: Mapping[str, Any], key: str) -> float:
    value = siem.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise ToolError("failed", reason="config")
    return value


def _connection(siem: Mapping[str, Any]) -> tuple[str, str]:
    """(ELK 주소, API 키). 없거나 주소가 틀리면 unavailable(config)."""
    url_env, key_env = siem.get("url_env"), siem.get("api_key_env")
    url = os.environ.get(url_env) if isinstance(url_env, str) and url_env else None
    key = os.environ.get(key_env) if isinstance(key_env, str) and key_env else None
    if not url or not key:
        raise ToolError("unavailable", reason="config")
    try:
        parsed = httpx.URL(url)
    except Exception:  # 주소 모양이 아니다. 메시지에 주소가 들어 있을 수 있어 남기지 않는다
        raise ToolError("unavailable", reason="config") from None
    if parsed.scheme not in ("http", "https") or not parsed.host or parsed.userinfo:
        raise ToolError("unavailable", reason="config")
    return url, key


def _verify(siem: Mapping[str, Any]) -> ssl.SSLContext | bool:
    """httpx.Client의 verify 값(#264). ca_cert_path가 비었거나 없으면 True(기본 신뢰 저장소).

    값이 있으면 그 CA 파일만 믿는 SSLContext다. 문자열이 아니거나 파일을 PEM 인증서로 읽지 못하면
    failed(config)이고 요청은 나가지 않는다. 경로는 details에 넣지 않는다.
    """
    path = siem.get("ca_cert_path", "")
    if not isinstance(path, str):
        raise ToolError("failed", reason="config")
    if not path:
        return True
    try:
        return ssl.create_default_context(cafile=path)
    except OSError:  # FileNotFoundError, IsADirectoryError, ssl.SSLError(PEM 아님)
        raise ToolError("failed", reason="config") from None


# 인자 검사


def _used_filters(args: Mapping[str, Any]) -> list[str]:
    return [name for name in FILTERS if args.get(name) is not None]


def _check(args: dict[str, Any], tools_config: Mapping[str, Any]) -> None:
    check_time_range(args, tools_config)
    if args["target"] not in _configured_targets(tools_config):
        raise ToolError("invalid_argument")  # 설정에서 뺀 대상
    allowed = TARGET_FILTERS[args["target"]]
    used = _used_filters(args)
    if len(used) > MAX_FILTERS or any(name not in allowed for name in used):
        raise ToolError("invalid_argument")
    for name in IP_FILTERS:
        if args.get(name) is not None:
            try:
                ipaddress.ip_network(args[name], strict=False)
            except ValueError:
                raise ToolError("invalid_argument") from None
    if "field" in args and args["field"] not in allowed:
        raise ToolError("invalid_argument")


# 쿼리


def _query(args: Mapping[str, Any], time_field: str) -> dict[str, Any]:
    time_range = {"gte": args["start_ms"], "lt": args["end_ms"], "format": "epoch_millis"}
    filters: list[dict[str, Any]] = [{"range": {time_field: time_range}}]
    for name in _used_filters(args):
        filters.append({"term": {FILTERS[name]: args[name]}})
    return {"bool": {"filter": filters}}


# HTTP


Clock = Callable[[], float]


def _search(
    ctx: CallContext,
    index: str,
    body: dict[str, Any],
    transport: httpx.BaseTransport | None,
    clock: Clock,
) -> dict[str, Any]:
    """POST /<index>/_search 한 번. JSON 객체를 돌려주거나 ToolError를 낸다."""
    siem = ctx.tools_config.get("siem", {})
    if not isinstance(siem, Mapping):
        raise ToolError("failed", reason="config")
    connect, read, deadline = (_positive(siem, key) for key in _TIMEOUT_KEYS)
    max_bytes = _positive(siem, "max_bytes")
    url, key = _connection(siem)
    verify = _verify(siem)
    timeout = httpx.Timeout(read, connect=connect)
    data = bytearray()
    started = clock()
    try:
        with httpx.Client(
            base_url=url,
            headers={"Authorization": f"ApiKey {key}"},
            timeout=timeout,
            follow_redirects=False,
            verify=verify,
            transport=transport,
        ) as client:
            with client.stream(
                "POST", f"/{index}/_search", json=body, follow_redirects=False
            ) as response:
                if response.status_code in (401, 403):
                    raise ToolError("failed", reason="auth")
                if not 200 <= response.status_code < 300:
                    raise ToolError("failed", reason="http_status")
                for chunk in response.iter_bytes():
                    data += chunk
                    if len(data) > max_bytes:
                        raise ToolError("failed", reason="too_large")
                    if clock() - started > deadline:
                        raise ToolError("timeout")
    except httpx.TimeoutException:
        raise ToolError("timeout") from None
    except httpx.HTTPError:
        # 연결 실패, 프로토콜 오류, 압축 해제 오류. 메시지에 주소가 들어 있을 수 있어 남기지 않는다
        raise ToolError("unavailable", reason="network") from None
    try:
        parsed = json.loads(data)
    except (ValueError, RecursionError):
        raise ToolError("failed", reason="response_shape") from None
    if not isinstance(parsed, dict):
        raise ToolError("failed", reason="response_shape")
    return parsed


def _shape_error() -> ToolError:
    return ToolError("failed", reason="response_shape")


def _total(data: Mapping[str, Any]) -> tuple[int, str]:
    outer = data.get("hits")
    total = outer.get("total") if isinstance(outer, dict) else None
    if not isinstance(total, dict):
        raise _shape_error()
    value, relation = total.get("value"), total.get("relation")
    if isinstance(value, bool) or not isinstance(value, int) or relation not in ("eq", "gte"):
        raise _shape_error()
    return value, relation


# 결과 모양


_MISSING = object()


def _lookup(source: Any, parts: list[str]) -> Any:
    """점 경로 값을 찾는다.

    중첩된 키({"source": {"ip": …}})와 점이 든 키({"source.ip": …})를 함께 본다.
    """
    if not parts:
        return source
    if not isinstance(source, dict):
        return _MISSING
    for size in range(len(parts), 0, -1):
        key = ".".join(parts[:size])
        if key in source:
            found = _lookup(source[key], parts[size:])
            if found is not _MISSING:
                return found
    return _MISSING


def _cap(value: Any, path: str, cut: list[str]) -> Any:
    """문자열을 FIELD_MAX_CHARS에서 자르고 자른 경로를 cut에 적는다."""
    if isinstance(value, str):
        if len(value) > FIELD_MAX_CHARS:
            cut.append(path)
            return value[:FIELD_MAX_CHARS] + CUT_MARK
        return value
    if isinstance(value, list):
        return [_cap(item, f"{path}[{i}]", cut) for i, item in enumerate(value)]
    if isinstance(value, dict):
        return {k: _cap(v, f"{path}.{k}", cut) for k, v in value.items()}
    return value


def _hit(hit: Any, fields: tuple[str, ...]) -> dict[str, Any]:
    if not isinstance(hit, dict):
        raise _shape_error()
    index, doc_id = hit.get("_index"), hit.get("_id")
    if not isinstance(index, str) or not index or not isinstance(doc_id, str) or not doc_id:
        raise _shape_error()
    source = hit.get("_source", {})
    if not isinstance(source, dict):
        raise _shape_error()
    picked: dict[str, Any] = {}
    cut: list[str] = []
    for field in fields:
        value = _lookup(source, field.split("."))
        if value is not _MISSING:
            picked[field] = _cap(value, field, cut)
    shaped: dict[str, Any] = {"siem_ref": f"{index}/{doc_id}", "fields": picked}
    if cut:
        shaped["truncated_fields"] = cut
    return shaped


def _query_siem(
    args: dict[str, Any], ctx: CallContext, transport: httpx.BaseTransport | None, clock: Clock
) -> dict[str, Any]:
    index, time_field = _target(args, ctx.tools_config)
    fields = (time_field, *(f for f in TARGET_FIELDS[args["target"]] if f != time_field))
    order = "asc" if args.get("sort") == "time_asc" else "desc"
    request = {
        "size": args["limit"],
        "query": _query(args, time_field),
        "sort": [{time_field: {"order": order, "unmapped_type": "date"}}],
        "_source": list(fields),
        "track_total_hits": TRACK_TOTAL_HITS,
    }
    data = _search(ctx, index, request, transport, clock)
    total, relation = _total(data)
    raw_hits = data["hits"].get("hits")
    if not isinstance(raw_hits, list):
        raise _shape_error()
    hits = [_hit(hit, fields) for hit in raw_hits]
    shown = list(hits)
    body: dict[str, Any] = {
        "source": SOURCE_NAME,
        "schema": SCHEMA_NAME,
        "target": args["target"],
        "total": total,
        "total_relation": relation,
        "hits": shown,
        "truncated": False,
        "omitted": 0,
    }
    # JSON 중간은 자르지 않는다. 뒤 히트부터 뺀다.
    while shown and not ctx.fits(body):
        shown.pop()
        body["truncated"] = True
        body["omitted"] = len(hits) - len(shown)
    return body


def _bucket(bucket: Any) -> dict[str, Any]:
    if not isinstance(bucket, dict):
        raise _shape_error()
    value, count = bucket.get("key"), bucket.get("doc_count")
    if isinstance(count, bool) or not isinstance(count, int):
        raise _shape_error()
    entry: dict[str, Any] = {"value": value, "count": count}
    if isinstance(value, str) and len(value) > VALUE_MAX_CHARS:
        entry["value"] = value[:VALUE_MAX_CHARS] + CUT_MARK
        entry["value_truncated"] = True
    return entry


def _count_siem(
    args: dict[str, Any], ctx: CallContext, transport: httpx.BaseTransport | None, clock: Clock
) -> dict[str, Any]:
    index, time_field = _target(args, ctx.tools_config)
    request = {
        "size": 0,
        "query": _query(args, time_field),
        "aggs": {"top": {"terms": {"field": FILTERS[args["field"]], "size": TOP_N}}},
        "track_total_hits": True,
    }
    data = _search(ctx, index, request, transport, clock)
    total, _ = _total(data)
    aggs = data.get("aggregations")
    top = aggs.get("top") if isinstance(aggs, dict) else None
    if not isinstance(top, dict) or not isinstance(top.get("buckets"), list):
        raise _shape_error()
    other = top.get("sum_other_doc_count", 0)
    if isinstance(other, bool) or not isinstance(other, int):
        raise _shape_error()
    buckets = [_bucket(b) for b in top["buckets"][:TOP_N]]
    body: dict[str, Any] = {
        "source": SOURCE_NAME,
        "schema": SCHEMA_NAME,
        "target": args["target"],
        "field": args["field"],
        "total": total,
        "buckets": buckets,
        "other_count": other,
        "truncated": False,
    }
    # 건수가 가장 적은(마지막) 항목부터 빼고, 뺀 건수는 other_count에 더한다.
    while buckets and not ctx.fits(body):
        body["other_count"] += buckets.pop()["count"]
        body["truncated"] = True
    return body


def siem_tools(
    transport: httpx.BaseTransport | None = None, clock: Clock = time.monotonic
) -> tuple[ToolSpec, ToolSpec]:
    """(query_siem, count_siem).

    transport·clock은 테스트가 바꿔 끼운다(기본: 실제 네트워크와 time.monotonic).
    """

    def query_handler(args: dict[str, Any], ctx: CallContext) -> dict[str, Any]:
        return _query_siem(args, ctx, transport, clock)

    def count_handler(args: dict[str, Any], ctx: CallContext) -> dict[str, Any]:
        return _count_siem(args, ctx, transport, clock)

    query_siem = ToolSpec(
        name="query_siem",
        description=(
            "SIEM(ELK)에서 시간 범위 안의 문서를 찾는다. 대상마다 정해진 필드만 돌려준다. "
            "히트마다 siem_ref(<_index>/<_id>)와 fields가 있다. "
            + _COMMON_DESCRIPTION
            + _target_lines()
        ),
        handler=query_handler,
        bundle="siem",
        result_kind="aggregate",
        limit_argument="limit",
        args=(TARGET_ARG, *TIME_RANGE_ARGS, *FILTER_ARGS, SORT_ARG),
        check=_check,
        check_config=_check_config,
    )
    count_siem = ToolSpec(
        name="count_siem",
        description=(
            "SIEM(ELK)에서 시간 범위 안의 문서를 field 값별로 세어 상위 10개와 건수, 전체 건수, "
            "나머지 건수(other_count)를 돌려준다. " + _COMMON_DESCRIPTION + _target_lines()
        ),
        handler=count_handler,
        bundle="siem",
        result_kind="aggregate",
        args=(TARGET_ARG, *TIME_RANGE_ARGS, FIELD_ARG, *FILTER_ARGS),
        check=_check,
        check_config=_check_config,
    )
    return query_siem, count_siem
