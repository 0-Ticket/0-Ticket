"""내부 데이터 도구(#211): get_alert, get_event, query_records.

alerts·events만 읽는다(읽기 역할 soc_agent_reader, 마이그레이션 0003). 결과는 records이고
id(alt_·evt_)가 근거 장부에 들어간다. 필터는 최상위 컬럼의 허용 목록뿐이고, 컬럼 이름과 정렬은
상수에서만 고른다. 모델이 만든 문자열은 매개변수로만 SQL에 들어간다.
"""

from collections.abc import Mapping
from typing import Any

from psycopg.types.json import Jsonb

from soc.contracts import to_datetime
from soc.tools.db import read_rows
from soc.tools.registry import Arg, CallContext, ToolError, ToolSpec

DAY_MS = 86_400_000
# 9999-12-31T23:59:59.999Z. 시간 인자는 epoch 밀리초다.
MAX_EPOCH_MS = 253_402_300_799_999
_UUID7 = r"[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
ENTITY_TYPES = ("ip", "host", "user", "domain", "url", "file_hash", "process")
SEARCH_MAX = 200

TIME_MS = "floor(extract(epoch FROM time) * 1000)::bigint AS time"
ORDER_BY = {"time_desc": "time DESC, id DESC", "time_asc": "time ASC, id ASC"}

_FULL = {
    "alerts": f"id, raw_id, {TIME_MS}, severity, title, rule_id, entities, assets, triage,"
    " ocsf, details",
    "events": f"id, raw_id, {TIME_MS}, ocsf_class, summary, entities, assets, ocsf, details",
}
_LIST = {
    "alert": ("alerts", f"id, {TIME_MS}, severity, title, rule_id, entities"),
    "event": ("events", f"id, {TIME_MS}, ocsf_class, summary, entities"),
}
_ALERT_ONLY = ("severity_min", "severity_max", "rule_id", "title_contains")
_EVENT_ONLY = ("ocsf_class", "summary_contains")

# 여러 도구가 함께 쓰는 인자
TIME_RANGE_ARGS = (
    Arg(
        "start_ms",
        "integer",
        required=True,
        minimum=0,
        maximum=MAX_EPOCH_MS,
        description="시작 시각(UTC epoch 밀리초, 포함)",
    ),
    Arg(
        "end_ms",
        "integer",
        required=True,
        minimum=0,
        maximum=MAX_EPOCH_MS,
        description="끝 시각(UTC epoch 밀리초, 제외). 시작과의 차이는 [tools] max_range_days 이하",
    ),
)
SORT_ARG = Arg("sort", "string", enum=tuple(ORDER_BY), description="정렬. 기본 time_desc")
ENTITY_ARGS = (
    Arg("entity_type", "string", enum=ENTITY_TYPES, description="엔티티 종류. entity_value와 함께"),
    Arg(
        "entity_value",
        "string",
        min_length=1,
        max_length=SEARCH_MAX,
        description="엔티티 값(정확히 일치). entity_type과 함께",
    ),
)


def contains_arg(name: str, what: str) -> Arg:
    return Arg(
        name,
        "string",
        min_length=1,
        max_length=SEARCH_MAX,
        description=f"{what}에 이 문자열이 들어 있는 것(대소문자 무시)",
    )


def check_time_range(args: Mapping[str, Any], tools_config: Mapping[str, Any]) -> None:
    span = args["end_ms"] - args["start_ms"]
    if span <= 0 or span > int(tools_config["max_range_days"]) * DAY_MS:
        raise ToolError("invalid_argument")


def like_pattern(text: str) -> str:
    """포함 검색 패턴. ILIKE의 %·_·\\는 글자 그대로 찾게 이스케이프한다(ESCAPE '\\')."""
    escaped = text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


LIKE = "ILIKE %s ESCAPE '\\'"


def time_where(args: Mapping[str, Any]) -> tuple[list[str], list[Any]]:
    return (
        ["time >= %s", "time < %s"],
        [to_datetime(args["start_ms"]), to_datetime(args["end_ms"])],
    )


def entity_where(args: Mapping[str, Any], where: list[str], params: list[Any]) -> None:
    if args.get("entity_type") is not None:
        where.append("entities @> %s")
        params.append(Jsonb([{"type": args["entity_type"], "value": args["entity_value"]}]))


def check_entity(args: Mapping[str, Any]) -> None:
    if (args.get("entity_type") is None) != (args.get("entity_value") is None):
        raise ToolError("invalid_argument")


def _get(table: str):
    def handler(args: dict[str, Any], ctx: CallContext) -> list[dict[str, Any]]:
        query = f"SELECT {_FULL[table]} FROM {table} WHERE id = %s"  # 표 이름은 상수다
        return read_rows(ctx, query, (args["id"],))

    return handler


def _check_query_records(args: dict[str, Any], tools_config: Mapping[str, Any]) -> None:
    check_time_range(args, tools_config)
    check_entity(args)
    other = _EVENT_ONLY if args["kind"] == "alert" else _ALERT_ONLY
    if any(args.get(name) is not None for name in other):
        raise ToolError("invalid_argument")  # kind와 맞지 않는 필터
    low, high = args.get("severity_min"), args.get("severity_max")
    if low is not None and high is not None and low > high:
        raise ToolError("invalid_argument")


def _query_records(args: dict[str, Any], ctx: CallContext) -> list[dict[str, Any]]:
    table, columns = _LIST[args["kind"]]
    where, params = time_where(args)
    filters = (
        ("severity_min", "severity >= %s", None),
        ("severity_max", "severity <= %s", None),
        ("rule_id", "rule_id = %s", None),
        ("title_contains", f"title {LIKE}", like_pattern),
        ("ocsf_class", "ocsf_class = %s", None),
        ("summary_contains", f"summary {LIKE}", like_pattern),
    )
    for name, clause, convert in filters:
        value = args.get(name)
        if value is not None:
            where.append(clause)
            params.append(convert(value) if convert else value)
    entity_where(args, where, params)
    order = ORDER_BY[args.get("sort") or "time_desc"]
    query = f"SELECT {columns} FROM {table} WHERE {' AND '.join(where)} ORDER BY {order} LIMIT %s"
    return read_rows(ctx, query, (*params, args["limit"]))


GET_ALERT = ToolSpec(
    name="get_alert",
    description="Alert 하나를 id(alt_…)로 읽는다. ocsf·details를 포함한 전체를 돌려준다.",
    handler=_get("alerts"),
    bundle="internal",
    result_kind="records",
    id_fields=("id",),
    args=(Arg("id", "string", required=True, pattern=f"alt_{_UUID7}", description="Alert id"),),
)

GET_EVENT = ToolSpec(
    name="get_event",
    description="Event 하나를 id(evt_…)로 읽는다. ocsf·details를 포함한 전체를 돌려준다.",
    handler=_get("events"),
    bundle="internal",
    result_kind="records",
    id_fields=("id",),
    args=(Arg("id", "string", required=True, pattern=f"evt_{_UUID7}", description="Event id"),),
)

QUERY_RECORDS = ToolSpec(
    name="query_records",
    description=(
        "시간 범위 안의 Alert(kind=alert) 또는 Event(kind=event) 목록을 찾는다. "
        "alert 필터: severity_min·severity_max·rule_id·title_contains. "
        "event 필터: ocsf_class·summary_contains. 엔티티 하나로 거를 수 있다. "
        "돌려주는 칸: id, time, severity 또는 ocsf_class, title 또는 summary, rule_id, entities."
    ),
    handler=_query_records,
    bundle="internal",
    result_kind="records",
    id_fields=("id",),
    limit_argument="limit",
    args=(
        Arg("kind", "string", required=True, enum=("alert", "event"), description="찾을 종류"),
        *TIME_RANGE_ARGS,
        Arg("severity_min", "integer", minimum=0, maximum=6, description="alert 심각도 하한"),
        Arg("severity_max", "integer", minimum=0, maximum=6, description="alert 심각도 상한"),
        Arg("rule_id", "string", min_length=1, max_length=SEARCH_MAX, description="alert 룰 ID"),
        contains_arg("title_contains", "alert 제목"),
        Arg(
            "ocsf_class",
            "integer",
            minimum=0,
            maximum=2_147_483_647,
            description="event OCSF class_uid",
        ),
        contains_arg("summary_contains", "event 요약"),
        *ENTITY_ARGS,
        SORT_ARG,
    ),
    check=_check_query_records,
)

INTERNAL_TOOLS = (GET_ALERT, GET_EVENT, QUERY_RECORDS)
