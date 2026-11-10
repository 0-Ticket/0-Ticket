"""내부 데이터·Web 도구와 에이전트 DB 읽기 역할(db 마커, #211).

임시 DB에 마이그레이션을 적용하고 tests/fixtures/tools/records.json의
손으로 만든 Alert·Event를 넣는다.
도구는 테스트가 만든 임시 LOGIN 역할(soc_agent_reader 멤버, 임의 비밀번호, 끝나면 삭제)로 접속한다.
"""

import asyncio
import copy
import json
import secrets
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from conftest import HiddenUrl
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.types.json import Jsonb
from test_agent_core import CONFIG
from tool_helpers import Caller, body_chars, parse

from soc.contracts import to_datetime, validate_contract
from soc.db.migrate import migrate
from soc.tools import Arg, ToolRegistry, ToolSpec, default_registry
from soc.tools.db import read_rows

pytestmark = pytest.mark.db

FIXTURE = Path(__file__).parent / "fixtures" / "tools" / "records.json"
T0 = 1793678578000
DAY = 86_400_000
READER = "soc_agent_reader"
ALL_TOOLS = ["get_alert", "get_event", "query_records", "query_http_flow", "summarize_http_flow"]


def load_records() -> dict[str, list[dict[str, Any]]]:
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    for alert in data["alerts"]:
        validate_contract("alert", alert)
    for event in data["events"]:
        validate_contract("event", event)
    return data


def insert_records(url: str, data: dict[str, list[dict[str, Any]]]) -> None:
    with psycopg.connect(url) as conn:
        for kind, table in (("alert", "alerts"), ("event", "events")):
            for record in data[f"{table}"]:
                conn.execute(
                    "INSERT INTO raw_records"
                    " (id, kind, siem_profile, siem_ref, fetched_at, original)"
                    " VALUES (%s, %s, 'test', %s, %s, %s) ON CONFLICT DO NOTHING",
                    (record["raw_id"], kind, record["raw_id"], to_datetime(T0), Jsonb({})),
                )
                row = dict(record)
                row["time"] = to_datetime(row["time"])
                for key in ("entities", "assets", "triage", "ocsf", "details"):
                    if key in row and row[key] is not None:
                        row[key] = Jsonb(row[key])
                query = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                    sql.Identifier(table),
                    sql.SQL(", ").join(map(sql.Identifier, row)),
                    sql.SQL(", ").join(sql.Placeholder() * len(row)),
                )
                conn.execute(query, list(row.values()))


@pytest.fixture
def migrated(temp_database: HiddenUrl) -> HiddenUrl:
    migrate(temp_database)
    insert_records(temp_database, load_records())
    return temp_database


@pytest.fixture
def reader_url(migrated: HiddenUrl, monkeypatch: pytest.MonkeyPatch) -> Iterator[HiddenUrl]:
    """soc_agent_reader 멤버인 임시 LOGIN 역할. 비밀번호는 임의 값이고 끝나면 역할을 지운다."""
    name = f"soc_test_reader_{secrets.token_hex(4)}"
    password = secrets.token_urlsafe(16)
    with psycopg.connect(migrated, autocommit=True) as admin:
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE {}").format(
                sql.Identifier(name), sql.Literal(password), sql.Identifier(READER)
            )
        )
    url = HiddenUrl(make_conninfo(migrated, user=name, password=password))
    monkeypatch.setenv("AGENT_DATABASE_URL", url)
    try:
        yield url
    finally:
        with psycopg.connect(migrated, autocommit=True) as admin:
            # 멤버십만 있고 권한·소유 객체가 없으므로 DB가 남아 있어도 바로 지울 수 있다
            admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(name)))


def tools_config(**tools: Any) -> dict[str, Any]:
    allowed = {"l1": ALL_TOOLS, "l2": ALL_TOOLS, "l3": ALL_TOOLS}
    return {**CONFIG, "tools": {**CONFIG["tools"], "allowed": allowed, **tools}}


def caller(config: dict[str, Any] | None = None, registry: ToolRegistry | None = None) -> Caller:
    return Caller(registry or default_registry(), config or tools_config())


def call(c: Caller, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    return parse(asyncio.run(c(name, arguments)))


def call_raw(c: Caller, name: str, arguments: dict[str, Any]) -> str:
    return asyncio.run(c(name, arguments))


RANGE = {"start_ms": T0 - DAY, "end_ms": T0 + DAY}
A1 = "alt_01a19f93-1150-7000-8000-000000000a01"
A2 = "alt_01a19f93-1150-7000-8000-000000000a02"
A3 = "alt_01a19f93-1150-7000-8000-000000000a03"
E = {i: f"evt_01a19f93-1150-7000-8000-000000000e0{i}" for i in range(1, 7)}


# 읽기 역할(마이그레이션 0003)


def test_reader_role_can_read_alerts_and_events(reader_url: str) -> None:
    with psycopg.connect(reader_url) as conn:
        assert conn.execute("SELECT count(*) FROM alerts").fetchone() == (3,)
        assert conn.execute("SELECT count(*) FROM events").fetchone() == (6,)


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT count(*) FROM raw_records",
        "SELECT count(*) FROM agent_logs",
        "SELECT count(*) FROM tickets",
        "SELECT count(*) FROM hunts",
        "SELECT count(*) FROM threat_news",
        "SELECT count(*) FROM schema_migrations",
        "UPDATE alerts SET title = 'x'",
        "DELETE FROM events",
        "INSERT INTO alerts (id, raw_id, time, severity, title, entities, assets, ocsf, details)"
        " VALUES ('alt_x', 'raw_01a19f93-1150-7000-8000-000000000b01', now(), 1, 't',"
        " '[]', '[]', '{}', '{}')",
    ],
)
def test_reader_role_is_denied_elsewhere(reader_url: str, statement: str) -> None:
    # 도구의 read-only 세션 설정이 아니라 역할 권한이 막는지 본다(일반 연결)
    with psycopg.connect(reader_url) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(statement)


def test_reader_role_migration_applies_to_another_database(
    migrated: str, other_temp_database: str
) -> None:
    """역할은 클러스터 전체에서 하나다. 이미 있어도 0003이 다른 DB에 적용된다."""
    applied = migrate(other_temp_database)
    assert "0003_agent_reader.sql" in applied
    with psycopg.connect(other_temp_database) as conn:
        granted = conn.execute(
            "SELECT table_name, privilege_type FROM information_schema.role_table_grants"
            " WHERE grantee = %s ORDER BY table_name",
            (READER,),
        ).fetchall()
    assert granted == [("alerts", "SELECT"), ("events", "SELECT")]


def test_reader_role_is_nologin(migrated: str) -> None:
    with psycopg.connect(migrated) as conn:
        (can_login,) = conn.execute(
            "SELECT rolcanlogin FROM pg_roles WHERE rolname = %s", (READER,)
        ).fetchone()
    assert can_login is False


# 내부 데이터 도구


def test_get_alert_returns_full_record_and_ledger_has_id(reader_url: str) -> None:
    c = caller()
    out = call(c, "get_alert", {"id": A1})
    [record] = out["records"]
    expected = next(a for a in load_records()["alerts"] if a["id"] == A1)
    assert record == expected
    assert A1 in c.session.evidence_ids
    assert out["call_id"] in c.session.evidence_ids
    assert c.rows[-1]["output"]["records"] == [expected]  # 모델에게 보인 결과(#278)


def test_get_event_and_missing_id(reader_url: str) -> None:
    c = caller()
    out = call(c, "get_event", {"id": E[5]})
    assert out["records"][0]["ocsf_class"] == 3002
    missing = call(c, "get_event", {"id": "evt_01a19f93-1150-7000-8000-0000000000ff"})
    assert missing["records"] == []


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("get_alert", {"id": E[1]}),  # 다른 접두사
        ("get_alert", {"id": "alt_1"}),
        ("query_records", {"kind": "alert", "start_ms": T0, "end_ms": T0 + 8 * DAY}),  # 7일 초과
        ("query_records", {"kind": "alert", "start_ms": T0, "end_ms": T0}),
        ("query_records", {"kind": "alert", "end_ms": T0}),  # 시간 범위 필수
        ("query_records", {"kind": "event", **RANGE, "severity_min": 1}),  # 종류와 맞지 않음
        ("query_records", {"kind": "alert", **RANGE, "ocsf_class": 4002}),
        ("query_records", {"kind": "alert", **RANGE, "severity_min": 5, "severity_max": 2}),
        ("query_records", {"kind": "alert", **RANGE, "entity_type": "ip"}),  # 값 없이 종류만
        ("query_records", {"kind": "alert", **RANGE, "entity_type": "mac", "entity_value": "x"}),
        ("query_records", {"kind": "alert", **RANGE, "raw_id": "x"}),  # 계약에 없는 필터
        ("query_records", {"kind": "alert", **RANGE, "order_by": "title"}),
        ("query_records", {"kind": "alert", **RANGE, "sort": "title"}),
        ("query_http_flow", {**RANGE, "status_code": 99}),
        ("query_http_flow", {**RANGE, "ocsf_class": 3002}),
        ("summarize_http_flow", {**RANGE, "limit": 5}),
    ],
)
def test_invalid_tool_arguments(reader_url: str, name: str, arguments: dict[str, Any]) -> None:
    out = call_raw(caller(), name, arguments)
    assert out.startswith(f"TOOL_ERROR tool={name} code=invalid_argument")


def ids(out: dict[str, Any]) -> list[str]:
    return [r["id"] for r in out["records"]]


def test_query_alerts_filters(reader_url: str) -> None:
    c = caller()
    assert ids(call(c, "query_records", {"kind": "alert", **RANGE})) == [A2, A1]
    asc = call(c, "query_records", {"kind": "alert", **RANGE, "sort": "time_asc"})
    assert ids(asc) == [A1, A2]
    wide = {"start_ms": T0 + 1 - 7 * DAY, "end_ms": T0 + 1}  # 딱 7일(상한)
    assert ids(call(c, "query_records", {"kind": "alert", **wide})) == [A1]  # A3는 10일 전
    sev = call(c, "query_records", {"kind": "alert", **RANGE, "severity_min": 3})
    assert ids(sev) == [A1]
    rule = call(c, "query_records", {"kind": "alert", **RANGE, "rule_id": "rule-cpu"})
    assert ids(rule) == [A2]
    title = call(c, "query_records", {"kind": "alert", **RANGE, "title_contains": "injection"})
    assert ids(title) == [A1]
    entity = {"entity_type": "ip", "entity_value": "203.0.113.10"}
    assert ids(call(c, "query_records", {"kind": "alert", **RANGE, **entity})) == [A1]
    one = call(c, "query_records", {"kind": "alert", **RANGE, "limit": 1})
    assert ids(one) == [A2]
    record = sev["records"][0]
    assert set(record) == {"id", "time", "severity", "title", "rule_id", "entities"}
    assert record["time"] == T0


def test_like_wildcards_are_literal(reader_url: str) -> None:
    c = caller()
    pct = call(c, "query_records", {"kind": "alert", **RANGE, "title_contains": "100%"})
    assert ids(pct) == [A2]
    assert ids(call(c, "query_records", {"kind": "alert", **RANGE, "title_contains": "%"})) == [A2]
    under = call(c, "query_records", {"kind": "alert", **RANGE, "title_contains": "e_a"})
    assert ids(under) == [A2]  # "usage_alert"만. _가 아무 글자로 쓰이지 않는다
    none = call(c, "query_records", {"kind": "alert", **RANGE, "title_contains": "SQL_"})
    assert ids(none) == []


def test_query_events_filters(reader_url: str) -> None:
    c = caller()
    every = call(c, "query_records", {"kind": "event", **RANGE})
    assert ids(every) == [E[6], E[5], E[4], E[3], E[2], E[1]]
    auth = call(c, "query_records", {"kind": "event", **RANGE, "ocsf_class": 3002})
    assert ids(auth) == [E[5]]
    summary = call(c, "query_records", {"kind": "event", **RANGE, "summary_contains": "ALICE"})
    assert ids(summary) == [E[5]]
    user = {"entity_type": "user", "entity_value": "alice"}
    assert ids(call(c, "query_records", {"kind": "event", **RANGE, **user})) == [E[5]]
    record = auth["records"][0]
    assert set(record) == {"id", "time", "ocsf_class", "summary", "entities"}
    assert set(ids(every)) <= c.session.evidence_ids


# Web 도구


def test_query_http_flow_reads_only_4002(reader_url: str) -> None:
    c = caller()
    out = call(c, "query_http_flow", RANGE)
    assert ids(out) == [E[4], E[3], E[2], E[1]]  # 3002·1007은 나오지 않는다
    first = out["records"][-1]
    assert first == {
        "id": E[1],
        "time": T0 + 1000,
        "summary": "GET /login.php 500",
        "entities": [{"type": "ip", "value": "203.0.113.10", "role": "src"}],
        "path": "/login.php",
        "method": "GET",
        "status_code": 500,
        "user_agent": "sqlmap/1.7",
        "src_ip": "203.0.113.10",
    }


def test_query_http_flow_filters(reader_url: str) -> None:
    c = caller()
    assert ids(call(c, "query_http_flow", {**RANGE, "src_ip": "198.51.100.7"})) == [E[3]]
    assert ids(call(c, "query_http_flow", {**RANGE, "method": "POST"})) == [E[2]]
    assert ids(call(c, "query_http_flow", {**RANGE, "status_code": 403})) == [E[4]]
    assert ids(call(c, "query_http_flow", {**RANGE, "path_contains": "login"})) == [E[2], E[1]]
    ua = call(c, "query_http_flow", {**RANGE, "user_agent_contains": "mozilla"})
    assert ids(ua) == [E[3]]
    # 3002 Event도 src_ip가 같지만 나오지 않는다
    src = call(c, "query_http_flow", {**RANGE, "src_ip": "203.0.113.10", "sort": "time_asc"})
    assert ids(src) == [E[1], E[2], E[4]]


def test_summarize_http_flow(reader_url: str) -> None:
    c = caller()
    out = call(c, "summarize_http_flow", RANGE)
    assert out["total"] == 4
    assert out["truncated"] is False
    fields = out["fields"]
    assert fields["method"] == [{"value": "GET", "count": 3}, {"value": "POST", "count": 1}]
    assert fields["path"][0] == {"value": "/login.php", "count": 2}
    assert fields["status_code"][0]["count"] == 2  # 200이 두 번
    assert fields["src_ip"][0] == {"value": "203.0.113.10", "count": 3}
    assert fields["user_agent"][0] == {"value": "sqlmap/1.7", "count": 3}
    # 집계는 call_id로만 인용한다
    assert c.session.evidence_ids == {out["call_id"]}


def test_summarize_http_flow_size_is_capped(migrated: str, reader_url: str) -> None:
    data = load_records()
    base = data["events"][0]
    extra = []
    for i in range(30):
        event = copy.deepcopy(base)
        event["id"] = f"evt_01a19f93-1150-7000-8000-0000000f{i:04x}"
        event["raw_id"] = f"raw_01a19f93-1150-7000-8000-0000000f{i:04x}"
        event["ocsf"]["http_request"]["user_agent"] = f"{i:02d}" + "A" * 3000
        event["ocsf"]["http_request"]["url"]["path"] = f"/p{i}/" + "B" * 500
        extra.append(event)
    insert_records(migrated, {"alerts": [], "events": extra})
    c = caller(tools_config())
    text = call_raw(c, "summarize_http_flow", RANGE)
    out = parse(text)
    assert out["total"] == 34
    for entries in out["fields"].values():
        assert len(entries) <= 10  # 필드별 상위 10개
    ua = out["fields"]["user_agent"]
    long = [e for e in ua if e.get("value_truncated")]
    assert long and all(len(e["value"]) <= 121 for e in long)  # 120자 + 표시
    assert body_chars(text) <= CONFIG["agent"]["l1"]["max_tool_result_chars"]

    small = {**CONFIG["agent"]["l1"], "max_tool_result_chars": 1500}
    tight = {**tools_config(), "agent": {**CONFIG["agent"], "l1": small}}
    text = call_raw(caller(tight), "summarize_http_flow", RANGE)
    out = parse(text)
    assert body_chars(text) <= 1500
    assert out["truncated"] is True
    counts = [e["count"] for e in out["fields"]["method"]]
    assert counts == sorted(counts, reverse=True)


# DB 오류


def test_statement_timeout_is_timeout(reader_url: str) -> None:
    def sleepy(args: dict[str, Any], ctx: Any) -> list[dict[str, Any]]:
        return read_rows(ctx, "SELECT pg_sleep(2) AS id", ())

    registry = ToolRegistry(
        [
            ToolSpec(
                name="sleepy",
                description="잠든다(테스트용)",
                handler=sleepy,
                bundle="test",
                result_kind="records",
                id_fields=("id",),
                args=(Arg("x", "integer"),),
            )
        ]
    )
    config = tools_config(statement_timeout_ms=100, allowed={"l1": ["sleepy"]})
    out = call_raw(Caller(registry, config), "sleepy", {})
    assert out.startswith("TOOL_ERROR tool=sleepy code=timeout")


def test_tool_session_is_read_only(reader_url: str, migrated: str) -> None:
    # 역할 권한이 뚫려도 세션이 읽기 전용이다(default_transaction_read_only=on)
    with psycopg.connect(migrated, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE TABLE scratch (x int)"))
        admin.execute(sql.SQL("GRANT INSERT ON scratch TO {}").format(sql.Identifier(READER)))

    def write(args: dict[str, Any], ctx: Any) -> list[dict[str, Any]]:
        return read_rows(ctx, "INSERT INTO scratch VALUES (1) RETURNING 'x' AS id", ())

    registry = ToolRegistry(
        [
            ToolSpec(
                name="write",
                description="쓰기 시도(테스트용)",
                handler=write,
                bundle="test",
                result_kind="records",
                id_fields=("id",),
            )
        ]
    )
    out = call_raw(Caller(registry, tools_config(allowed={"l1": ["write"]})), "write", {})
    assert out.startswith("TOOL_ERROR tool=write code=failed")
    with psycopg.connect(migrated) as conn:
        assert conn.execute("SELECT count(*) FROM scratch").fetchone() == (0,)
