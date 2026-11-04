"""Web 도구(#211): query_http_flow, summarize_http_flow.

events에서 HTTP Activity(ocsf_class = 4002)만 읽는다. 쓰는 OCSF 필드의 JSON 경로는 아래 상수다.
summarize_http_flow는 필드별 상위 10개 값과 건수만 돌려준다. 값마다 120자로 자르고, 그래도
결과 한도를 넘으면 필드마다 건수가 적은 항목부터 뺀다. 집계라 call_id(agl_)로만 인용한다.
"""

from collections.abc import Mapping
from typing import Any

from soc.tools.db import read_many, read_rows
from soc.tools.internal import (
    LIKE,
    ORDER_BY,
    SORT_ARG,
    TIME_MS,
    TIME_RANGE_ARGS,
    check_time_range,
    contains_arg,
    like_pattern,
    time_where,
)
from soc.tools.registry import CUT_MARK, Arg, CallContext, ToolError, ToolSpec

HTTP_ACTIVITY = 4002
# 필드 이름 → ocsf 안의 JSON 경로(OCSF 1.9.0 HTTP Activity)
HTTP_FIELDS: dict[str, tuple[str, ...]] = {
    "path": ("http_request", "url", "path"),
    "method": ("http_request", "http_method"),
    "status_code": ("http_response", "code"),
    "user_agent": ("http_request", "user_agent"),
    "src_ip": ("src_endpoint", "ip"),
}
TOP_N = 10
VALUE_MAX_CHARS = 120

FILTER_ARGS = (
    *TIME_RANGE_ARGS,
    Arg("src_ip", "string", min_length=1, max_length=64, description="출발지 IP(정확히 일치)"),
    Arg(
        "method",
        "string",
        min_length=1,
        max_length=16,
        pattern="[A-Za-z]+",
        description="HTTP 메서드(정확히 일치, 예: GET)",
    ),
    Arg("status_code", "integer", minimum=100, maximum=599, description="HTTP 응답 코드"),
    contains_arg("path_contains", "URL 경로"),
    contains_arg("user_agent_contains", "User-Agent"),
)


def _check(args: dict[str, Any], tools_config: Mapping[str, Any]) -> None:
    check_time_range(args, tools_config)


def _where(args: Mapping[str, Any]) -> tuple[str, list[Any]]:
    where, params = time_where(args)
    where.insert(0, "ocsf_class = %s")
    params.insert(0, HTTP_ACTIVITY)
    exact = (("src_ip", "src_ip"), ("method", "method"), ("status_code", "status_code"))
    for arg, field in exact:
        if args.get(arg) is not None:
            where.append("ocsf #>> %s::text[] = %s")
            params += [list(HTTP_FIELDS[field]), str(args[arg])]
    for arg, field in (("path_contains", "path"), ("user_agent_contains", "user_agent")):
        if args.get(arg) is not None:
            where.append(f"ocsf #>> %s::text[] {LIKE}")
            params += [list(HTTP_FIELDS[field]), like_pattern(args[arg])]
    return " AND ".join(where), params


def _query_http_flow(args: dict[str, Any], ctx: CallContext) -> list[dict[str, Any]]:
    fields = ", ".join(f"ocsf #> %s::text[] AS {name}" for name in HTTP_FIELDS)  # 이름은 상수
    where, params = _where(args)
    order = ORDER_BY[args.get("sort") or "time_desc"]
    query = (
        f"SELECT id, {TIME_MS}, summary, entities, {fields} FROM events"
        f" WHERE {where} ORDER BY {order} LIMIT %s"
    )
    select_params = [list(path) for path in HTTP_FIELDS.values()]
    return read_rows(ctx, query, (*select_params, *params, args["limit"]))


def _summarize_http_flow(args: dict[str, Any], ctx: CallContext) -> dict[str, Any]:
    where, params = _where(args)
    queries: list[tuple[str, list[Any]]] = [
        (f"SELECT count(*) AS n FROM events WHERE {where}", params)
    ]
    for path in HTTP_FIELDS.values():
        query = (
            "SELECT value, n FROM ("
            f"SELECT ocsf #> %s::text[] AS value, count(*) AS n FROM events WHERE {where}"
            " GROUP BY 1) AS s ORDER BY n DESC, value::text ASC NULLS LAST LIMIT %s"
        )
        queries.append((query, [list(path), *params, TOP_N]))
    results = read_many(ctx, queries)
    fields = {
        name: [_entry(row["value"], row["n"]) for row in rows]
        for name, rows in zip(HTTP_FIELDS, results[1:], strict=True)
    }
    body: dict[str, Any] = {"total": results[0][0]["n"], "fields": fields, "truncated": False}
    # JSON 중간은 자르지 않는다. 항목이 가장 많은 필드에서 건수가 가장 적은(마지막) 항목부터 뺀다.
    while not ctx.fits(body):
        name = max(fields, key=lambda f: len(fields[f]))
        if not fields[name]:
            raise ToolError("failed")
        fields[name].pop()
        body["truncated"] = True
    return body


def _entry(value: Any, count: int) -> dict[str, Any]:
    entry: dict[str, Any] = {"value": value, "count": count}
    if isinstance(value, str) and len(value) > VALUE_MAX_CHARS:
        entry["value"] = value[:VALUE_MAX_CHARS] + CUT_MARK
        entry["value_truncated"] = True
    return entry


QUERY_HTTP_FLOW = ToolSpec(
    name="query_http_flow",
    description=(
        "시간 범위 안의 HTTP 요청 Event(OCSF 4002) 목록을 찾는다. "
        "돌려주는 칸: id, time, summary, entities, path, method, status_code, user_agent, src_ip."
    ),
    handler=_query_http_flow,
    bundle="web",
    result_kind="records",
    id_fields=("id",),
    limit_argument="limit",
    args=(*FILTER_ARGS, SORT_ARG),
    check=_check,
)

SUMMARIZE_HTTP_FLOW = ToolSpec(
    name="summarize_http_flow",
    description=(
        "시간 범위 안의 HTTP 요청 Event(OCSF 4002)를 집계한다. 전체 건수와 "
        "path·method·status_code·user_agent·src_ip별 상위 10개 값과 건수를 돌려준다. "
        "집계는 이 호출의 call_id로 인용한다."
    ),
    handler=_summarize_http_flow,
    bundle="web",
    result_kind="aggregate",
    args=FILTER_ARGS,
    check=_check,
)

WEB_TOOLS = (QUERY_HTTP_FLOW, SUMMARIZE_HTTP_FLOW)
