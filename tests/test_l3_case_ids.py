"""L3가 Case 검색 도구 결과에서 인용할 수 있는 Case ID를 읽는 규칙과 입력 예산(#393, D-088).

검색 결과 모양은 지어내지 않는다. 실제 search_confirmed_cases 핸들러를 가짜 임베더·FakeDb로
돌려 Agent Log에 남는 tool 줄(Caller.rows)을 그대로 case_ids_in에 넣는다(#392 약속:
results[].case.id). DB가 필요한 처리는 test_l3_hunt_db.py가 본다.
"""

import asyncio
import contextlib
import math
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest
from case_search_helpers import (
    NAME,
    QUERY,
    SERVICE,
    FakeDb,
    VectorEmbedder,
    cid,
    config,
    make_service,
)
from tool_helpers import Caller, parse

from soc.agent import AgentResult, AgentTask
from soc.agent.config import load_config as load_agent_config
from soc.agent.runner import first_call_size
from soc.ids import new_id
from soc.l3.config import load_config
from soc.l3.hunt import store
from soc.l3.hunt.hypothesize import hypothesize
from soc.l3.hunt.prompts import load_prompt
from soc.l3.hunt.settings import lookback_window, read_hunt_settings
from soc.l3.hunt.verify import HuntVerifier
from soc.store import StoreError
from soc.tools import confirmed_cases as module
from soc.tools import default_registry


def tool_row(
    monkeypatch: pytest.MonkeyPatch,
    args: dict[str, Any] | None = None,
    *,
    service: Any = None,
    cfg: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], str]:
    """도구를 한 번 불러 Agent Log의 tool 줄과 모델에게 간 문자열을 돌려준다."""
    monkeypatch.setattr(module, "read_many", FakeDb())
    caller = Caller(
        default_registry(),
        cfg or config(),
        stage="l3",
        services={SERVICE: service or make_service()},
    )
    out = asyncio.run(caller(NAME, args or {"query": QUERY, "limit": 1}))
    (row,) = [r for r in caller.rows if r["kind"] == "tool"]
    return row, out


def only(n: int) -> Any:
    """질의가 Case n 하나만 0.99 이상으로 맞춘다(4는 [0,0,1], 5는 [0,0.6,0.8])."""
    vector = {4: [0.0, 0.0, 1.0], 5: [0.0, 0.6, 0.8]}[n]
    return make_service(embedder=VectorEmbedder({QUERY: vector}))


# case_ids_in: 실제 도구가 Agent Log에 남긴 줄


@pytest.mark.parametrize(
    ("n", "result_max_chars"),
    [
        (4, 30_000),  # 줄이지 않음
        (4, 6_500),  # 단계 2
        (4, 5_000),  # 단계 4
        (4, 4_100),  # 단계 5
        (4, 4_000),  # 기본 한도: 단계 6(권고 조치는 개수만)
        (4, 1_500),  # 단계 7(Case·개수만, detail_omitted)
        (5, 8_000),
        (5, 4_000),
        (5, 1_500),
    ],
)
def test_the_case_id_is_read_at_every_reduction_level(
    monkeypatch: pytest.MonkeyPatch, n: int, result_max_chars: int
) -> None:
    cfg = config(section={"min_score": 0.99, "result_max_chars": result_max_chars})

    row, _ = tool_row(monkeypatch, service=only(n), cfg=cfg)

    assert row["outcome"] != "error"
    assert store.case_ids_in(row["output"]) == [cid(n)]


def test_the_stage_seven_result_really_is_the_one_without_details(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cfg = config(section={"min_score": 0.99, "result_max_chars": 1_500})

    row, _ = tool_row(monkeypatch, service=only(4), cfg=cfg)

    assert row["output"]["results"][0]["detail_omitted"] is True  # 이 줄에서도 case.id는 있다


def test_every_returned_case_is_read_in_the_result_order(monkeypatch: pytest.MonkeyPatch) -> None:
    row, _ = tool_row(monkeypatch, {"query": QUERY, "limit": 2})

    assert store.case_ids_in(row["output"]) == [cid(1), cid(2)]  # 점수 1.0, 0.8


def test_the_call_id_is_not_a_case_id(monkeypatch: pytest.MonkeyPatch) -> None:
    row, out = tool_row(monkeypatch)
    shown = parse(out)  # 모델에게 간 본문에는 call_id가 있다

    assert shown["call_id"].startswith("agl_")
    assert "call_id" not in row["output"]  # Agent Log에는 핸들러 결과만 남는다
    assert store.case_ids_in(shown) == [cid(1)]  # 본문을 넣어도 agl_는 읽지 않는다


def test_no_match_has_no_case_id(monkeypatch: pytest.MonkeyPatch) -> None:
    service = make_service(embedder=VectorEmbedder({QUERY: [0.0, 0.0, -1.0]}))

    row, _ = tool_row(monkeypatch, service=service)

    assert row["output"]["reason"] == "no_match"
    assert store.case_ids_in(row["output"]) == []


def test_no_data_has_no_case_id(monkeypatch: pytest.MonkeyPatch) -> None:
    empty = make_service(points={})
    empty.store.drop_collection()

    row, _ = tool_row(monkeypatch, service=empty)

    assert row["output"] == {"status": "no_data", "reason": "no_index"}
    assert store.case_ids_in(row["output"]) == []


def test_an_error_line_has_no_case_id(monkeypatch: pytest.MonkeyPatch) -> None:
    class Broken:
        def search(self, *_: object, **__: object) -> None:
            raise StoreError("down")

    row, _ = tool_row(monkeypatch, service=make_service(store=Broken()))

    assert row["outcome"] == "error"
    assert store.case_ids_in(row["output"]) == []  # 오류 줄의 output은 고정 문구다


@pytest.mark.parametrize(
    "output",
    [
        None,
        "TOOL_ERROR tool=search_confirmed_cases code=failed",
        [],
        {},
        {"status": "no_data", "results": [{"case": {"id": "cas_x"}}]},
        {"status": "ok"},
        {"status": "ok", "results": "x"},
        {"status": "ok", "results": [None, 1, {}, {"case": None}, {"case": {"id": 5}}]},
    ],
)
def test_a_malformed_output_gives_no_case_id(output: Any) -> None:
    assert store.case_ids_in(output) == []


# 입력 예산: 가설 생성 run이 두 도구를 함께 쓸 때(D-088)

ACTOR_RESULT_CHARS = 4_100  # #389 실측 2,700~4,100자의 위쪽
SIEM_RESULT_CHARS = 8_000  # [agent.l3] max_tool_result_chars
ESCAPE_MARGIN = 1.05  # 도구 결과를 입력 항목으로 다시 직렬화하면 따옴표 이스케이프로 약 4% 늘어난다


def worst_task() -> tuple[AgentTask, dict[str, Any]]:
    """뉴스 5건(요약 상한 1,000자)·Case 3건(요약 1,000자)이 꽉 찬 가설 생성 입력."""
    config = load_agent_config()
    hunt = read_hunt_settings(load_config()["l3"])
    text = "가" * 1_000
    news = [
        {
            "id": n,
            "source": "boannews",
            "title": "제목" * 50,
            "summary": text,
            "published_at": 1_764_000_000_000,
        }
        for n in range(1, hunt.news_limit + 1)
    ]
    cases = [
        {
            "id": cid(n),
            "title": "제목" * 50,
            "summary": text,
            "severity": 4,
            "entities": [{"type": "ip", "value": f"203.0.113.{n}", "role": "src"}] * 5,
        }
        for n in range(1, hunt.case_limit + 1)
    ]
    window = lookback_window(hunt, datetime(2026, 11, 28, tzinfo=UTC))
    task = AgentTask(
        stage="l3",
        task="l3_hypothesize",
        prompt=load_prompt("l3_hypothesize"),
        data={"news": news, "cases": cases, "max_hypotheses": 1, "window": window},
        output_contract="hunt_hypotheses",
        cited_ids=lambda output: (),
        subject_type="hunt",
        subject_id=new_id("hrn"),
        allowed_evidence_ids=(),
    )
    return task, config


def test_the_first_call_with_the_fullest_input_fits_the_budget() -> None:
    task, cfg = worst_task()

    chars, limit = first_call_size(task, cfg)

    assert limit == 64_000
    assert chars < 20_000  # 첫 호출은 예산의 일부일 뿐이다. 나머지는 도구 결과가 쓴다


def test_five_actor_calls_two_case_searches_and_a_siem_result_fit_the_budget() -> None:
    task, cfg = worst_task()
    chars, limit = first_call_size(task, cfg)
    case_cap = cfg["tools"]["confirmed_cases"]["result_max_chars"]

    last_call = chars + math.ceil(
        (5 * ACTOR_RESULT_CHARS + 2 * case_cap + SIEM_RESULT_CHARS) * ESCAPE_MARGIN
    )

    assert last_call <= limit  # 마지막(최종 답) 호출이 가장 크다. 48,000자로는 51,000자대라 넘었다


def test_the_turns_cover_the_tool_calls_the_prompt_allows() -> None:
    cfg = load_agent_config()

    # 행위자 5 + Case 검색 2 + SIEM 조회 2 + 최종 답 1 + 형식 오류 재요청 1
    assert cfg["agent"]["l3"]["max_turns"] >= 5 + 2 + 2 + 1 + 1


# 가설 생성·검증의 처리(DB 없이: store 함수를 바꿔 끼운다). 실제 Agent Log 읽기는 db 테스트가 본다

CAS = "cas_01a19f93-1150-7000-8000-000000000001"  # 입력(cases)에 있는 Case
UNKNOWN = "cas_01a19f93-1392-7000-8000-000000000777"
NOW = datetime(2026, 11, 28, tzinfo=UTC)
NEWS = {"id": 1, "source": "boannews", "title": "t", "summary": "s", "published_at": 1}


class NoConn:
    def transaction(self) -> Any:
        return contextlib.nullcontext()


def hypothesize_with(
    monkeypatch: pytest.MonkeyPatch, searched: Any, case_ids: list[str]
) -> tuple[Any, list[dict[str, Any]]]:
    """searched는 case_search_ids의 반환값 또는 던질 예외."""
    saved: list[dict[str, Any]] = []

    def case_search_ids(*_: Any) -> Any:
        if isinstance(searched, Exception):
            raise searched
        return searched

    monkeypatch.setattr(store, "attack_names", lambda *_: {"T1190": "x"})
    monkeypatch.setattr(store, "recent_news", lambda *_, **__: [NEWS])
    monkeypatch.setattr(store, "recent_cases", lambda *_, **__: [{"id": CAS}])
    monkeypatch.setattr(store, "actor_tool_calls", lambda *_: (0, {}))
    monkeypatch.setattr(store, "case_search_ids", case_search_ids)
    monkeypatch.setattr(store, "insert_hunts", lambda conn, hunts: saved.extend(hunts))
    output = {
        "hypotheses": [
            {
                "hypothesis": "가설",
                "attack_techniques": ["T1190"],
                "news_ids": [1],
                "case_ids": case_ids,
            }
        ]
    }

    def run(task: AgentTask) -> AgentResult:
        return AgentResult(ok=True, output=output, failure=None, detail=None, run_id=new_id("run"))  # type: ignore[arg-type]

    settings = read_hunt_settings(load_config()["l3"])
    return hypothesize(NoConn(), settings, run=run, now=NOW), saved  # type: ignore[arg-type]


def test_a_searched_case_is_kept_with_the_recent_cases_and_unknown_ones_are_counted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, saved = hypothesize_with(monkeypatch, (1, [cid(1)]), [CAS, cid(1), UNKNOWN])

    sources = saved[0]["details"]["sources"]
    assert sources["case_ids"] == [CAS, cid(1)]
    assert result.dropped_refs == 1
    assert "case_search" not in sources


def test_without_a_search_only_the_recent_cases_are_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, saved = hypothesize_with(monkeypatch, (0, []), [CAS, cid(1)])

    sources = saved[0]["details"]["sources"]
    assert sources["case_ids"] == [CAS]
    assert result.dropped_refs == 1
    assert "case_search" not in sources  # 도구를 안 불렀으면 예전과 같다


def test_an_unreadable_agent_log_allows_only_the_recent_cases_and_marks_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result, saved = hypothesize_with(monkeypatch, psycopg.OperationalError("down"), [CAS, cid(1)])

    assert len(saved) == 1  # Hunt는 저장한다
    sources = saved[0]["details"]["sources"]
    assert sources["case_ids"] == [CAS]
    assert sources["case_search"] == {"unavailable": True}
    assert result.dropped_refs == 1


def verified_details(monkeypatch: pytest.MonkeyPatch, searched: Any) -> dict[str, Any]:
    def case_search_ids(*_: Any) -> Any:
        if isinstance(searched, Exception):
            raise searched
        return searched

    monkeypatch.setattr(store, "record_entities", lambda *_: ([], 0))
    monkeypatch.setattr(store, "case_search_ids", case_search_ids)
    verifier = HuntVerifier("postgresql://unused", read_hunt_settings(load_config()["l3"]))
    hunt = {"details": {"sources": {"news": [], "case_ids": []}}}
    output = {
        "result": "inconclusive",
        "confidence": 0.5,
        "reason": "r",
        "evidence_ids": [],
        "entities": [],
    }

    done = verifier._verified(NoConn(), hunt, output, 1, new_id("run"))  # type: ignore[arg-type]

    return done["details"]


def test_verify_records_the_cases_the_run_read(monkeypatch: pytest.MonkeyPatch) -> None:
    details = verified_details(monkeypatch, (2, [cid(1), cid(2)]))

    assert details["verify_cases"] == {"tool_calls": 2, "case_ids": [cid(1), cid(2)]}
    assert details["sources"] == {"news": [], "case_ids": []}  # 가설 생성 쪽 기록은 그대로


def test_verify_counts_a_search_that_found_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    assert verified_details(monkeypatch, (1, []))["verify_cases"] == {
        "tool_calls": 1,
        "case_ids": [],
    }


def test_verify_without_a_search_has_no_verify_cases_key(monkeypatch: pytest.MonkeyPatch) -> None:
    assert "verify_cases" not in verified_details(monkeypatch, (0, []))


def test_verify_marks_cases_unavailable_when_the_agent_log_cannot_be_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    details = verified_details(monkeypatch, psycopg.OperationalError("down"))

    assert details["verify_cases"] == {"unavailable": True}


# case_search_ids가 읽는 agent_logs의 모양(DB 없이: 마이그레이션 파일과 기록기의 줄을 대조한다)

AGENT_LOGS_MIGRATION = (
    Path(__file__).parents[1] / "src" / "soc" / "db" / "migrations" / "0001_common_tables.sql"
)


def declared(column: str) -> list[str]:
    """agent_logs의 `<column> text NOT NULL CHECK (<column> IN (...))`에 적힌 값 목록."""
    text = AGENT_LOGS_MIGRATION.read_text(encoding="utf-8")
    table = text[text.index("CREATE TABLE agent_logs") :]
    match = re.search(rf"{column} text NOT NULL CHECK \({column} IN \(([^)]*)\)\)", table)
    assert match, column
    return re.findall(r"'([^']*)'", match.group(1))


def test_the_migration_still_declares_the_columns_case_search_ids_reads() -> None:
    text = AGENT_LOGS_MIGRATION.read_text(encoding="utf-8")
    table = text[text.index("CREATE TABLE agent_logs") :]

    for snippet in (
        "run_id text NOT NULL",
        "seq integer NOT NULL",
        "name text NOT NULL",
        "output jsonb CHECK (output IS NULL OR jsonb_typeof(output) <> 'null')",
    ):
        assert snippet in table, snippet
    assert declared("kind") == ["model", "tool"]
    assert declared("outcome") == ["ok", "error"]


def test_a_tool_row_the_recorder_writes_keeps_the_agent_logs_constraints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    row, _ = tool_row(monkeypatch)

    assert row["kind"] in declared("kind") and row["kind"] == "tool"
    assert row["outcome"] in declared("outcome")
    assert row["stage"] in declared("stage") and row["stage"] == "l3"
    assert row["subject_type"] in declared("subject_type")
    assert row["name"] == NAME and row["seq"] >= 1
    assert isinstance(row["output"], dict)  # JSON null이 아니다(output 칸 CHECK)


class RecordingConn:
    def __init__(self, rows: list[tuple[str, Any]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, Any]] = []

    def execute(self, query: str, params: Any) -> Any:
        self.calls.append((query, params))
        return self

    def fetchall(self) -> list[tuple[str, Any]]:
        return self.rows


def test_case_search_ids_reads_one_run_tool_rows_in_order_and_skips_error_lines() -> None:
    first = {"status": "ok", "results": [{"case": {"id": cid(1)}}, {"case": {"id": cid(2)}}]}
    again = {"status": "ok", "results": [{"case": {"id": cid(2)}}, {"case": {"id": cid(3)}}]}
    conn = RecordingConn(
        [
            ("ok", first),
            ("error", "TOOL_ERROR tool=search_confirmed_cases code=unavailable"),
            ("ok", {"status": "no_data", "reason": "no_index"}),
            ("ok", again),
        ]
    )

    calls, ids = store.case_search_ids(conn, "run_x", store.CASE_SEARCH_TOOL)  # type: ignore[arg-type]

    assert (calls, ids) == (4, [cid(1), cid(2), cid(3)])  # 호출 수에는 오류 줄도 센다
    ((query, params),) = conn.calls
    assert params == ("run_x", "search_confirmed_cases")
    # 읽는 열·조건은 모두 agent_logs에 있는 이름이다
    table = AGENT_LOGS_MIGRATION.read_text(encoding="utf-8")
    for word in ("agent_logs", "outcome", "output", "run_id", "kind", "name", "seq"):
        assert word in query and word in table
    assert "kind = 'tool'" in query and "ORDER BY seq" in query
