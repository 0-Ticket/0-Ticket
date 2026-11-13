"""로컬 ATT&CK·KEV 조회 도구의 응답 모양과 입력 검사(#311, D-052).

DB 읽기(read_many)를 가짜로 바꿔 DB 없이 확인한다. 실제 PostgreSQL과 읽기 역할은
tests/test_tools_local_intel_db.py(db 마커)가 본다.
"""

import asyncio
import socket
from datetime import UTC, date, datetime
from typing import Any

import httpx
import pytest
from test_agent_core import CONFIG
from tool_helpers import Caller, body_chars, parse

from soc.tools import ToolConfigError, default_registry
from soc.tools import local_intel as module
from soc.tools.local_intel import normalize_cve_id, normalize_technique_id

COLLECTED = datetime(2026, 11, 13, 1, 0, tzinfo=UTC)
LOCAL_INTEL = {"attack_version": "20.0", "description_max_chars": 600, "list_max_items": 20}
NAMES = ["get_attack_technique", "search_attack_techniques", "get_cve"]


def config(*, local_intel: dict | None = None, max_chars: int | None = None) -> dict[str, Any]:
    tools = {
        **CONFIG["tools"],
        "allowed": {"l2": NAMES},
        "local_intel": LOCAL_INTEL if local_intel is None else local_intel,
    }
    agent = CONFIG["agent"]
    if max_chars is not None:
        agent = {**agent, "l2": {**agent["l2"], "max_tool_result_chars": max_chars}}
    return {**CONFIG, "tools": tools, "agent": agent}


class FakeDb:
    """SQL 종류별로 미리 넣은 행을 돌려주고, 받은 문장과 값을 남긴다."""

    def __init__(self, **rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, tuple]] = []

    @staticmethod
    def kind(sql: str) -> str:
        if "count(collected_at)" in sql:
            return "attack_state"
        if "technique_id LIKE" in sql:
            return "children"
        if "ILIKE" in sql:
            return "search"
        if "FROM attack_techniques" in sql and "detection_sources" in sql:
            return "technique"
        if "FROM attack_techniques" in sql:
            return "parent"
        if "intel_source_state" in sql:
            return "kev_state"
        if "count(*) AS total FROM kev_entries" in sql:
            return "kev_count"
        return "kev_row"

    def __call__(self, ctx: Any, queries: list) -> list[list[dict[str, Any]]]:
        out = []
        for sql, params in queries:
            kind = self.kind(sql)
            self.calls.append((kind, tuple(params)))
            out.append(self.rows.get(kind, []))
        return out


def use(monkeypatch: pytest.MonkeyPatch, **rows: list[dict[str, Any]]) -> FakeDb:
    db = FakeDb(**rows)
    monkeypatch.setattr(module, "read_many", db)
    return db


def call(name: str, arguments: dict[str, Any], cfg: dict[str, Any] | None = None) -> str:
    caller = Caller(default_registry(), cfg or config(), stage="l2")
    return asyncio.run(caller(name, arguments))


def result(name: str, arguments: dict[str, Any], cfg: dict[str, Any] | None = None):
    return parse(call(name, arguments, cfg))


ATTACK_STATE = [{"total": 4, "filled": 4, "collected_at": COLLECTED}]
T1190 = {
    "technique_id": "T1190",
    "name": "Exploit Public-Facing Application",
    "tactics": ["initial-access"],
    "description": "Adversaries may attack a public-facing application.",
    "detection_sources": ["Application Log Content", "Network Traffic Content"],
}
CHILDREN = [
    {"technique_id": "T1190.001", "name": "Child one", "total": 2},
    {"technique_id": "T1190.002", "name": "Child two", "total": 2},
]


# --- 입력 정규화 ---


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("T1190", "T1190"),
        ("attack.T1190", "T1190"),
        ("attack.t1190", "T1190"),
        ("t1059.001", "T1059.001"),
        ("ATTACK.T1059.001", "T1059.001"),
    ],
)
def test_technique_id_forms_are_normalized(value: str, expected: str) -> None:
    assert normalize_technique_id(value) == expected


@pytest.mark.parametrize(
    "value",
    ["", "T119", "T11900", "T1190.1", "T1190 ", " T1190", "T1190\n", "attack.", "x.T1190", "1190"],
)
def test_bad_technique_id_is_rejected(value: str) -> None:
    with pytest.raises(ValueError):
        normalize_technique_id(value)


def test_cve_id_is_normalized_and_validated() -> None:
    assert normalize_cve_id("cve-2021-44228") == "CVE-2021-44228"
    for bad in ("CVE-2021-123", "CVE-21-1234", "CVE-2021-1234\n", "2021-44228", "CVE-2021-1234; x"):
        with pytest.raises(ValueError):
            normalize_cve_id(bad)


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("get_attack_technique", {"technique_id": "T119"}),
        ("get_attack_technique", {"technique_id": "T1190'; DROP TABLE x"}),
        ("get_attack_technique", {"technique_id": ""}),
        ("get_attack_technique", {}),
        ("search_attack_techniques", {"query": "x"}),
        ("search_attack_techniques", {"query": "a" * 101}),
        ("search_attack_techniques", {"query": "shell", "limit": 0}),
        ("search_attack_techniques", {"query": "shell", "limit": 101}),
        ("get_cve", {"cve_id": "CVE-2021-1"}),
        ("get_cve", {"cve_id": "CVE-2021-44228 OR 1=1"}),
    ],
)
def test_bad_arguments_never_reach_the_database(
    monkeypatch: pytest.MonkeyPatch, name: str, arguments: dict[str, Any]
) -> None:
    db = use(monkeypatch)
    assert call(name, arguments).startswith(f"TOOL_ERROR tool={name} code=invalid_argument")
    assert db.calls == []


# --- get_attack_technique ---


def test_technique_forms_give_the_same_result(monkeypatch: pytest.MonkeyPatch) -> None:
    db = use(monkeypatch, attack_state=ATTACK_STATE, technique=[T1190], children=CHILDREN)
    bodies = [
        {
            k: v
            for k, v in result("get_attack_technique", {"technique_id": value}).items()
            if k != "call_id"
        }  # call_id는 호출마다 다르다
        for value in ("T1190", "attack.T1190", "attack.t1190")
    ]
    assert bodies[0] == bodies[1] == bodies[2]
    assert [params for kind, params in db.calls if kind == "technique"] == [("20.0", "T1190")] * 3
    body = bodies[0]
    assert body["status"] == "found"
    assert body["name"] == "Exploit Public-Facing Application"
    assert body["tactics"] == ["initial-access"]
    assert body["description"] == "Adversaries may attack a public-facing application."
    assert body["description_truncated"] is False
    assert body["detection_sources"] == ["Application Log Content", "Network Traffic Content"]
    assert body["subtechnique_count"] == 2
    assert [s["technique_id"] for s in body["subtechniques"]] == ["T1190.001", "T1190.002"]
    assert body["attack_version"] == "20.0"
    assert body["attack_collected_at"] == "2026-11-13T01:00:00Z"


def test_subtechnique_has_parent_and_no_children_query(monkeypatch: pytest.MonkeyPatch) -> None:
    db = use(
        monkeypatch,
        attack_state=ATTACK_STATE,
        technique=[{**T1190, "technique_id": "T1190.001", "name": "Child one"}],
        parent=[{"technique_id": "T1190", "name": "Exploit Public-Facing Application"}],
    )
    body = result("get_attack_technique", {"technique_id": "T1190.001"})
    assert body["parent"] == {
        "technique_id": "T1190",
        "name": "Exploit Public-Facing Application",
    }
    assert "subtechniques" not in body
    assert ("parent", ("20.0", "T1190")) in db.calls
    assert "children" not in [kind for kind, _ in db.calls]


def test_unknown_technique_is_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    use(monkeypatch, attack_state=ATTACK_STATE)
    body = result("get_attack_technique", {"technique_id": "T9999"})
    assert body["status"] == "not_found"
    assert body["attack_version"] == "20.0"
    assert "name" not in body


@pytest.mark.parametrize(
    ("state", "reason"),
    [
        ({"total": 0, "filled": 0, "collected_at": None}, "attack_version_missing"),
        ({"total": 3, "filled": 0, "collected_at": None}, "attack_detail_not_collected"),
    ],
)
def test_missing_copy_is_no_data_not_not_found(
    monkeypatch: pytest.MonkeyPatch, state: dict, reason: str
) -> None:
    use(monkeypatch, attack_state=[state], technique=[T1190])
    for name, arguments in (
        ("get_attack_technique", {"technique_id": "T1190"}),
        ("search_attack_techniques", {"query": "public"}),
    ):
        body = result(name, arguments)
        body.pop("call_id")
        assert body == {"status": "no_data", "reason": reason, "attack_version": "20.0"}


def test_description_and_lists_are_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    long = {**T1190, "description": "x" * 50, "detection_sources": [f"S{i}" for i in range(5)]}
    use(monkeypatch, attack_state=ATTACK_STATE, technique=[long], children=CHILDREN)
    cap = {"attack_version": "20.0", "description_max_chars": 10, "list_max_items": 2}
    body = result("get_attack_technique", {"technique_id": "T1190"}, config(local_intel=cap))
    assert body["description"] == "x" * 10 + "…"
    assert body["description_truncated"] is True
    assert body["detection_sources"] == ["S0", "S1"]
    assert body["detection_source_count"] == 5


def test_children_query_is_limited_by_config(monkeypatch: pytest.MonkeyPatch) -> None:
    db = use(monkeypatch, attack_state=ATTACK_STATE, technique=[T1190])
    result("get_attack_technique", {"technique_id": "T1190"})
    assert ("children", ("20.0", "T1190.%", 20)) in db.calls


def test_result_is_trimmed_to_the_tool_result_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    many = [{"technique_id": f"T1190.{i:03d}", "name": "n" * 60, "total": 20} for i in range(20)]
    use(monkeypatch, attack_state=ATTACK_STATE, technique=[T1190], children=many)
    text = call("get_attack_technique", {"technique_id": "T1190"}, config(max_chars=900))
    body = parse(text)
    assert body["status"] == "found"
    assert 0 < len(body["subtechniques"]) < 20
    assert body["subtechnique_count"] == 20  # 줄여도 전체 수는 남는다
    assert body_chars(text) <= 900


# --- search_attack_techniques ---


def test_search_escapes_wildcards_and_uses_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [{**T1190, "matched": 7, "description": "d" * 300}]
    db = use(monkeypatch, attack_state=ATTACK_STATE, search=rows)
    body = result("search_attack_techniques", {"query": "100%_a\\b", "limit": 3})
    pattern = "%100\\%\\_a\\\\b%"
    assert ("search", ("20.0", pattern, pattern, pattern, 3)) in db.calls
    assert body["status"] == "ok"
    assert body["matched"] == 7
    assert body["returned"] == 1
    assert body["results"][0]["technique_id"] == "T1190"
    assert body["results"][0]["description_excerpt"] == "d" * 160 + "…"
    assert "description" not in body["results"][0]


def test_search_default_limit_and_no_match(monkeypatch: pytest.MonkeyPatch) -> None:
    db = use(monkeypatch, attack_state=ATTACK_STATE)
    body = result("search_attack_techniques", {"query": "nothing"})
    assert body["matched"] == 0
    assert body["results"] == []
    assert ("search", ("20.0", "%nothing%", "%nothing%", "%nothing%", 20)) in db.calls


# --- get_cve ---

KEV_STATE = [
    {
        "catalog_version": "2026.11.03",
        "released_at": datetime(2026, 11, 3, 20, 0, tzinfo=UTC),
        "collected_at": COLLECTED,
    }
]
KEV_ROW = {
    "cve_id": "CVE-2026-0001",
    "vulnerability_name": "Example VPN Remote Code Execution Vulnerability",
    "vendor_project": "Example",
    "product": "Example VPN",
    "short_description": "Example VPN contains a remote code execution vulnerability.",
    "known_ransomware_use": "Known",
    "date_added": date(2026, 11, 3),
    "due_date": date(2026, 11, 24),
    "required_action": "Apply mitigations per vendor instructions.",
}


def test_cve_in_kev(monkeypatch: pytest.MonkeyPatch) -> None:
    db = use(monkeypatch, kev_state=KEV_STATE, kev_count=[{"total": 3}], kev_row=[KEV_ROW])
    body = result("get_cve", {"cve_id": "cve-2026-0001"})
    assert ("kev_row", ("CVE-2026-0001",)) in db.calls
    assert body["status"] == "found"
    assert body["vendor_project"] == "Example"
    assert body["product"] == "Example VPN"
    assert body["known_ransomware_use"] == "Known"
    assert body["date_added"] == "2026-11-03"
    assert body["due_date"] == "2026-11-24"
    assert body["required_action"] == "Apply mitigations per vendor instructions."
    assert body["kev_catalog_version"] == "2026.11.03"
    assert body["kev_released_at"] == "2026-11-03T20:00:00Z"
    assert body["kev_collected_at"] == "2026-11-13T01:00:00Z"
    assert body["text_truncated"] is False


def test_cve_missing_from_kev_is_not_in_kev(monkeypatch: pytest.MonkeyPatch) -> None:
    use(monkeypatch, kev_state=KEV_STATE, kev_count=[{"total": 3}])
    body = result("get_cve", {"cve_id": "CVE-2021-44228"})
    assert body["status"] == "not_in_kev"
    assert body["cve_id"] == "CVE-2021-44228"
    assert body["kev_collected_at"] == "2026-11-13T01:00:00Z"
    assert "vendor_project" not in body


@pytest.mark.parametrize(
    "rows",
    [
        {"kev_state": [], "kev_count": [{"total": 3}]},  # 수집 상태가 없다
        {"kev_state": KEV_STATE, "kev_count": [{"total": 0}]},  # 항목이 하나도 없다
    ],
)
def test_empty_kev_copy_is_no_data_not_not_in_kev(
    monkeypatch: pytest.MonkeyPatch, rows: dict
) -> None:
    use(monkeypatch, **rows)
    body = result("get_cve", {"cve_id": "CVE-2021-44228"})
    assert body["status"] == "no_data"
    assert body["reason"] == "kev_not_collected"


def test_cve_text_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    row = {**KEV_ROW, "short_description": "y" * 40, "required_action": "z" * 40}
    use(monkeypatch, kev_state=KEV_STATE, kev_count=[{"total": 1}], kev_row=[row])
    cap = {**LOCAL_INTEL, "description_max_chars": 15}
    body = result("get_cve", {"cve_id": "CVE-2026-0001"}, config(local_intel=cap))
    assert body["description"] == "y" * 15 + "…"
    assert body["required_action"] == "z" * 15 + "…"
    assert body["text_truncated"] is True


# --- 설정과 네트워크 ---


@pytest.mark.parametrize(
    "bad",
    [
        {},
        {**LOCAL_INTEL, "attack_version": ""},
        {**LOCAL_INTEL, "attack_version": 20},
        {**LOCAL_INTEL, "description_max_chars": 0},
        {**LOCAL_INTEL, "list_max_items": True},
        {"attack_version": "20.0", "description_max_chars": 600},
    ],
)
def test_bad_tool_config_stops_the_run(bad: dict) -> None:
    with pytest.raises(ToolConfigError):
        Caller(default_registry(), config(local_intel=bad), stage="l2")


def test_tools_make_no_network_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("네트워크를 쓰면 안 된다")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    use(
        monkeypatch,
        attack_state=ATTACK_STATE,
        technique=[T1190],
        search=[{**T1190, "matched": 1}],
        kev_state=KEV_STATE,
        kev_count=[{"total": 1}],
        kev_row=[KEV_ROW],
    )
    assert result("get_attack_technique", {"technique_id": "T1190"})["status"] == "found"
    assert result("search_attack_techniques", {"query": "public"})["status"] == "ok"
    assert result("get_cve", {"cve_id": "CVE-2026-0001"})["status"] == "found"
    assert "httpx" not in vars(module)
