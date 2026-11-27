"""get_attack_actor의 응답 모양, 정렬, 크기 조절, 입력 검사(#389, D-052).

DB 읽기(read_many)를 가짜로 바꿔 DB 없이 확인한다. 실제 PostgreSQL과 읽기 역할은
tests/test_tools_attack_actor_db.py(db 마커)가 본다.
"""

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from test_agent_core import CONFIG
from tool_helpers import Caller, body_chars, parse

from soc.tools import ToolConfigError, default_registry
from soc.tools import local_intel as module

NAME = "get_attack_actor"
COLLECTED = datetime(2026, 11, 27, 1, 0, tzinfo=UTC)
LOG_COMPONENTS = ["Network Traffic Content", "Network Traffic Flow"]
LOCAL_INTEL = {
    "attack_version": "20.0",
    "description_max_chars": 600,
    "list_max_items": 20,
    "log_data_components": LOG_COMPONENTS,
    "actor_techniques_max": 20,
}
ATTACK_STATE = [{"total": 4, "filled": 4, "collected_at": COLLECTED}]


def config(*, local_intel: dict | None = None, max_chars: int | None = None) -> dict[str, Any]:
    tools = {
        **CONFIG["tools"],
        "allowed": {"l3": [NAME]},
        "local_intel": LOCAL_INTEL if local_intel is None else local_intel,
    }
    agent = CONFIG["agent"]
    if max_chars is not None:
        agent = {**agent, "l3": {**agent["l3"], "max_tool_result_chars": max_chars}}
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
        if "count(*) AS total FROM attack_actors" in sql:
            return "actor_count"
        if "FROM attack_actor_techniques" in sql:
            return "techniques"
        return "actors"

    def __call__(self, ctx: Any, queries: list) -> list[list[dict[str, Any]]]:
        out = []
        for sql, params in queries:
            kind = self.kind(sql)
            self.calls.append((kind, tuple(params)))
            out.append(self.rows.get(kind, []))
        return out


def use(monkeypatch: pytest.MonkeyPatch, **rows: list[dict[str, Any]]) -> FakeDb:
    rows.setdefault("attack_state", ATTACK_STATE)
    rows.setdefault("actor_count", [{"total": 4}])
    db = FakeDb(**rows)
    monkeypatch.setattr(module, "read_many", db)
    return db


def call(arguments: dict[str, Any], cfg: dict[str, Any] | None = None) -> str:
    caller = Caller(default_registry(), cfg or config(), stage="l3")
    return asyncio.run(caller(NAME, arguments))


def result(arguments: dict[str, Any], cfg: dict[str, Any] | None = None) -> dict[str, Any]:
    return parse(call(arguments, cfg))


def technique(technique_id: str, sources: list[str], actors: list[str] | None = None) -> dict:
    return {
        "technique_id": technique_id,
        "name": f"Name of {technique_id}",
        "detection_sources": sources,
        "actors": actors or ["G0001"],
    }


GROUP = [{"actor_id": "G0001", "kind": "group", "name": "Alpha Group"}]


def test_found_lists_actors_and_techniques_with_log_components(monkeypatch) -> None:
    use(
        monkeypatch,
        actors=GROUP,
        techniques=[technique("T1190", ["Network Traffic Content", "Command Execution"])],
    )

    body = result({"name": "Alpha Group"})

    assert body["status"] == "found"
    assert body["attack_version"] == "20.0"
    assert body["attack_collected_at"] == "2026-11-27T01:00:00Z"
    assert body["actors"] == [{"actor_id": "G0001", "kind": "group", "name": "Alpha Group"}]
    assert body["techniques"] == [
        {
            "technique_id": "T1190",
            "name": "Name of T1190",
            "log_components": ["Network Traffic Content"],
            "actors": ["G0001"],
        }
    ]
    assert (body["technique_total"], body["returned"], body["omitted"]) == (1, 1, 0)


def test_name_is_stripped_and_passed_as_a_parameter(monkeypatch) -> None:
    db = use(monkeypatch, actors=GROUP, techniques=[technique("T1190", [])])

    result({"name": "  alpha group  "})

    queried = [params for kind, params in db.calls if kind in ("actors", "techniques")]
    assert queried
    for params in queried:
        assert "alpha group" in params  # 앞뒤 공백만 지운다. 대소문자는 DB가 무시한다
        assert "  alpha group  " not in params


def test_order_is_more_log_overlap_first_then_technique_id(monkeypatch) -> None:
    both = ["Network Traffic Content", "Network Traffic Flow"]
    one = ["Network Traffic Flow"]
    use(
        monkeypatch,
        actors=GROUP,
        techniques=[
            technique("T1059.001", []),
            technique("T1190", one),
            technique("T1059", one),
            technique("T1566", both),
            technique("T1059.004", one),
            technique("T1001", []),
        ],
    )

    ids = [t["technique_id"] for t in result({"name": "Alpha Group"})["techniques"]]

    # 겹침 2개 → 1개(ID순) → 0개(ID순). 겹치지 않는 기법이 뒤를 채운다
    assert ids == ["T1566", "T1059", "T1059.004", "T1190", "T1001", "T1059.001"]


def test_at_most_the_configured_number_of_techniques(monkeypatch) -> None:
    rows = [technique(f"T{n:04d}", []) for n in range(1000, 1025)]
    rows.append(technique("T9999", ["Network Traffic Flow"]))  # 겹치는 기법은 ID가 커도 앞에 온다
    use(monkeypatch, actors=GROUP, techniques=rows)

    body = result({"name": "Alpha Group"})

    assert body["returned"] == len(body["techniques"]) == 20
    assert (body["technique_total"], body["omitted"]) == (26, 6)
    assert body["techniques"][0]["technique_id"] == "T9999"
    assert [t["technique_id"] for t in body["techniques"][1:3]] == ["T1000", "T1001"]


def test_name_shared_by_several_actors_returns_each_technique_once_with_its_actors(
    monkeypatch,
) -> None:
    actors = [
        {"actor_id": "G0001", "kind": "group", "name": "Shared Name"},
        {"actor_id": "S0001", "kind": "malware", "name": "Shared Name"},
    ]
    use(
        monkeypatch,
        actors=actors,
        techniques=[
            technique("T1190", [], ["G0001", "S0001"]),
            technique("T1059.004", [], ["S0001"]),
        ],
    )

    body = result({"name": "shared name"})

    assert [a["actor_id"] for a in body["actors"]] == ["G0001", "S0001"]
    assert {t["technique_id"]: t["actors"] for t in body["techniques"]} == {
        "T1190": ["G0001", "S0001"],
        "T1059.004": ["S0001"],
    }
    assert body["technique_total"] == 2


def test_actor_without_techniques_is_found_with_an_empty_list(monkeypatch) -> None:
    use(monkeypatch, actors=GROUP, techniques=[])

    body = result({"name": "Alpha Group"})

    assert body["status"] == "found"
    assert body["techniques"] == []
    assert (body["technique_total"], body["returned"], body["omitted"]) == (0, 0, 0)


def test_unknown_name_is_not_found(monkeypatch) -> None:
    use(monkeypatch, actors=[], techniques=[])

    body = result({"name": "Nobody"})

    assert body["status"] == "not_found"
    assert body["attack_version"] == "20.0"
    assert "techniques" not in body


def test_no_data_when_attack_or_actors_are_not_collected(monkeypatch) -> None:
    use(monkeypatch, attack_state=[{"total": 0, "filled": 0, "collected_at": None}])
    body = result({"name": "Alpha Group"})
    assert (body["status"], body["reason"]) == ("no_data", "attack_version_missing")

    use(monkeypatch, actor_count=[{"total": 0}])
    body = result({"name": "Alpha Group"})
    assert (body["status"], body["reason"]) == ("no_data", "attack_actors_not_collected")


def big_sample() -> dict[str, list[dict[str, Any]]]:
    """한 이름에 행위자 30개가 걸리고 기법 이름이 긴 큰 샘플."""
    actors = [
        {"actor_id": f"S{n:04d}", "kind": "malware", "name": f"Shared Name Variant {n} " + "x" * 80}
        for n in range(1, 31)
    ]
    techniques = [
        {
            "technique_id": f"T{n:04d}",
            "name": "Long technique name " + "y" * 120,
            "detection_sources": LOG_COMPONENTS if n % 2 else [],
            "actors": [a["actor_id"] for a in actors],
        }
        for n in range(1000, 1060)
    ]
    return {"actors": actors, "techniques": techniques}


def test_big_result_is_trimmed_from_the_back_and_reports_what_was_left_out(monkeypatch) -> None:
    use(monkeypatch, **big_sample())
    limit = 6000

    text = call({"name": "Shared Name"}, config(max_chars=limit))
    body = parse(text)

    assert body["status"] == "found"  # 호출이 실패하지 않는다
    assert body_chars(text) <= limit
    assert body["technique_total"] == 60
    assert 0 < body["returned"] == len(body["techniques"]) < 20
    assert body["omitted"] == 60 - body["returned"] > 40  # 상한 20개에 더해 크기로 뺀 수도 센다
    # 남는 것은 앞의 기법(겹침이 많은 순)이다
    assert body["techniques"][0]["technique_id"] == "T1001"
    assert body["actors_omitted"] == 30 - len(body["actors"]) == 10  # 행위자는 상한 20개만


def test_even_a_tiny_limit_does_not_fail_the_call(monkeypatch) -> None:
    use(monkeypatch, **big_sample())

    body = result({"name": "Shared Name"}, config(max_chars=350))

    assert body["status"] == "found"
    assert body["techniques"] == []
    assert body["actors"] == []
    assert (body["omitted"], body["actors_omitted"]) == (60, 30)


def test_actors_are_capped_by_list_max_items(monkeypatch) -> None:
    use(monkeypatch, **big_sample())
    small = {**LOCAL_INTEL, "list_max_items": 5}

    body = result({"name": "Shared Name"}, config(local_intel=small, max_chars=8000))

    assert len(body["actors"]) <= 5
    assert body["actors_omitted"] == 30 - len(body["actors"])


@pytest.mark.parametrize(
    "arguments",
    [{}, {"name": ""}, {"name": "a"}, {"name": "   "}, {"name": "x" * 101}, {"name": 5}],
)
def test_bad_input_never_reaches_the_db(monkeypatch, arguments: dict[str, Any]) -> None:
    db = use(monkeypatch, actors=GROUP)

    text = call(arguments)

    assert "invalid_argument" in text
    assert db.calls == []


@pytest.mark.parametrize(
    "bad",
    [
        {k: v for k, v in LOCAL_INTEL.items() if k != "log_data_components"},
        {k: v for k, v in LOCAL_INTEL.items() if k != "actor_techniques_max"},
        {**LOCAL_INTEL, "log_data_components": []},
        {**LOCAL_INTEL, "log_data_components": "Network Traffic Content"},
        {**LOCAL_INTEL, "log_data_components": ["ok", 1]},
        {**LOCAL_INTEL, "actor_techniques_max": 0},
        {**LOCAL_INTEL, "actor_techniques_max": True},
    ],
)
def test_bad_config_stops_the_session(bad: dict[str, Any]) -> None:
    with pytest.raises(ToolConfigError):
        Caller(default_registry(), config(local_intel=bad), stage="l3")


def test_old_local_intel_config_still_works_for_the_other_tools() -> None:
    old = {
        k: v
        for k, v in LOCAL_INTEL.items()
        if k not in ("log_data_components", "actor_techniques_max")
    }
    cfg = config(local_intel=old)
    cfg["tools"] = {**cfg["tools"], "allowed": {"l2": ["get_cve"]}}

    Caller(
        default_registry(), cfg, stage="l2"
    )  # 새 키가 없어도 get_cve만 허용하면 설정 오류가 아니다
