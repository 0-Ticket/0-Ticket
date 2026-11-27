"""Case 검색 도구 테스트가 함께 쓰는 도우미(#392, D-087).

샘플은 tests/fixtures/case_search/cases.json이다(손으로 설계하고 생성기로 한 번 만든 파일).
- Case 1: 승인 당시 Artifact가 둘(1·2차)이고 최신(2차)만 쓴다. 권고 조치 셋(seq 순), 티켓 둘,
  알럿 셋.
- Case 2: Artifact가 없다(dev_seed처럼 직접 넣은 Case).
- Case 3: origin = l3 Ticket(Alert 없음)과 일반 Ticket이 섞여 있다.
- Case 4: 긴 Case(문장 칸 300자, 타임라인·기법·권고 조치 4, 티켓 3, 알럿 6). 도구 한도 4000을
  넘고 줄이기
  네 단계째에야 들어가는 크기다(맨 끝 단계가 약 4,640자라 기본 한도 4000으로는 못 맞춘다).
- Case 5: 극단(타임라인·권고 조치 12, 티켓 12, 알럿 24, 문장 칸 900자)이라 어느 단계에서도
  4,000자에 못 맞춘다.
FakeDb는 도구가 읽는 다섯 문장(SQL 상수)에 샘플에서 계산한 행을 돌려준다. 실제 SQL은 db 마커
테스트가 본다.
"""

import json
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path
from typing import Any

from qdrant_client import QdrantClient
from test_agent_core import CONFIG

from soc.case_index.runtime import ConfirmedCasesService
from soc.contracts import to_datetime
from soc.store import VectorStore
from soc.store.config import EmbedderSettings, QdrantSettings, StoreSettings
from soc.tools import confirmed_cases as module

FIXTURE = Path(__file__).parent / "fixtures" / "case_search" / "cases.json"
SAMPLE: dict[str, Any] = json.loads(FIXTURE.read_text(encoding="utf-8"))
NAME = module.NAME
SERVICE = module.SERVICE
SETTINGS = StoreSettings(
    qdrant=QdrantSettings(url_env="QDRANT_URL"),
    embedder=EmbedderSettings(
        model_id="BAAI/bge-m3", revision="5617a9f61b028005a4858fdac845db406aefb181"
    ),
)
# config/default.toml [tools.confirmed_cases]와 같은 값(test_agent_config가 같은 값을 확인한다)
SECTION: dict[str, Any] = {
    "limit_default": 2,
    "limit_max": 3,
    "min_score": 0.5,
    "query_max_chars": 200,
    "text_max_chars": 600,
    "list_max_items": 10,
    "result_max_chars": 4000,
}


def without_call_id(result: Mapping[str, Any]) -> dict[str, Any]:
    """결과에서 call_id만 뺀다. 도구를 부를 때마다 새 agl_ ID가 붙어 두 호출은 같을 수 없다.

    나머지(results 전체)는 그대로 둔다. 비교 전에 call_id가 agl_로 시작하는지 확인한다.
    """
    assert str(result["call_id"]).startswith("agl_"), result["call_id"]
    return {k: v for k, v in result.items() if k != "call_id"}


def cid(n: int) -> str:
    return f"cas_01a19f93-1392-7000-8000-{n:012d}"


def pid(n: int) -> str:
    return cid(n).removeprefix("cas_")


class VectorEmbedder:
    """텍스트마다 정해 둔 3차원 벡터를 돌려준다. 코사인 값을 마음대로 만들기 위해서다."""

    dimension = 3

    def __init__(self, vectors: Mapping[str, list[float]]) -> None:
        self.vectors = dict(vectors)
        self.texts: list[str] = []

    def embed(self, text: str) -> list[float]:
        self.texts.append(text)
        return self.vectors[text]


# 질의 QUERY(= [1, 0, 0])와의 코사인: Case 1은 1.0, 2는 0.8, 3는 0.6, 4·5는 0.0
QUERY = "qq"
POINTS = {
    1: [1.0, 0.0, 0.0],
    2: [0.8, 0.6, 0.0],
    3: [0.6, 0.8, 0.0],
    4: [0.0, 0.0, 1.0],
    5: [0.0, 0.6, 0.8],
}


def make_service(
    points: Mapping[int, list[float]] | None = None,
    embedder: Any = None,
    store: Any = None,
) -> ConfirmedCasesService:
    embedder = embedder or VectorEmbedder({QUERY: [1.0, 0.0, 0.0]})
    if store is None:
        store = VectorStore("confirmed_cases", embedder, SETTINGS, client=QdrantClient(":memory:"))
        store.ensure_collection()
        for n, vector in (POINTS if points is None else points).items():
            store.upsert(pid(n), vector, {})
    return ConfirmedCasesService(embedder, store)


def config(
    *,
    section: Mapping[str, Any] | None = None,
    allowed: Mapping[str, list[str]] | None = None,
    max_chars: int | None = None,
) -> dict[str, Any]:
    tools = {
        **CONFIG["tools"],
        "allowed": {"l3": [NAME]} if allowed is None else dict(allowed),
        "confirmed_cases": {**SECTION, **(section or {})},
    }
    agent = CONFIG["agent"]
    if max_chars is not None:
        agent = {**agent, "l3": {**agent["l3"], "max_tool_result_chars": max_chars}}
    return {**CONFIG, "tools": tools, "agent": agent}


# 샘플에서 도구가 읽는 다섯 문장의 행을 계산한다. 실제 SQL의 열과 같은 이름·순서를 쓴다.


def _dt(ms: int) -> datetime:
    return to_datetime(ms)


def _by_id(table: str) -> dict[str, dict[str, Any]]:
    return {row["id"]: row for row in SAMPLE[table]}


def _alert_ids(ticket_ids: list[str]) -> list[str]:
    tickets = _by_id("tickets")
    return sorted({a for t in ticket_ids for a in tickets[t]["alert_ids"]})


def _latest_artifacts(case_ids: list[str]) -> list[dict[str, Any]]:
    incident_ids = {c["incident_id"] for c in SAMPLE["cases"] if c["id"] in case_ids}
    latest: dict[str, dict[str, Any]] = {}
    for artifact in SAMPLE["incident_artifacts"]:
        if artifact["incident_id"] not in incident_ids:
            continue
        seen = latest.get(artifact["incident_id"])
        if seen is None or artifact["analysis_round"] > seen["analysis_round"]:
            latest[artifact["incident_id"]] = artifact
    return [latest[key] for key in sorted(latest)]


def rows_for(sql: str, params: tuple) -> list[dict[str, Any]]:
    case_ids = list(params[-1])
    cases = [c for c in SAMPLE["cases"] if c["id"] in case_ids]
    incidents = _by_id("incidents")
    tickets = _by_id("tickets")
    alerts = _by_id("alerts")
    if sql == module.CASES_SQL:
        rows = []
        for case in cases:
            ticket_ids = incidents[case["incident_id"]]["ticket_ids"]
            rows.append(
                {
                    **{
                        k: case[k]
                        for k in ("id", "incident_id", "title", "summary", "severity", "entities")
                    },
                    "confirmed_at": _dt(case["confirmed_at"]),
                    "status": case["status"],
                    "ticket_total": len(ticket_ids),
                    "alert_total": len(_alert_ids(ticket_ids)),
                }
            )
        return sorted(rows, key=lambda r: r["id"])
    latest = _latest_artifacts(case_ids)
    if sql == module.ARTIFACT_SQL:
        keys = (
            "id incident_id analysis_round verdict timeline techniques impact cause "
            "further_risk evidence_ids"
        ).split()
        return [{k: a[k] for k in keys} for a in latest]
    if sql == module.PROPOSALS_SQL:
        ids = {a["id"] for a in latest}
        keys = "artifact_id kind seq priority title detail rationale".split()
        found = [p for p in SAMPLE["incident_proposals"] if p["artifact_id"] in ids]
        found.sort(key=lambda p: (p["artifact_id"], p["seq"]))
        return [{k: p[k] for k in keys} for p in found]
    limit = params[0]
    rows = []
    for case in sorted(cases, key=lambda c: c["id"]):
        ticket_ids = incidents[case["incident_id"]]["ticket_ids"]
        if sql == module.TICKETS_SQL:
            found = sorted(
                (tickets[t] for t in ticket_ids), key=lambda t: (t["created_at"], t["id"])
            )
            for ticket in found[:limit]:
                rows.append(
                    {
                        "case_id": case["id"],
                        "id": ticket["id"],
                        "origin": ticket["origin"],
                        "title": ticket["title"],
                        "created_at": _dt(ticket["created_at"]),
                    }
                )
        elif sql == module.ALERTS_SQL:
            found = sorted(
                (alerts[a] for a in _alert_ids(ticket_ids)),
                key=lambda a: (-a["severity"], a["time"], a["id"]),
            )
            for alert in found[:limit]:
                rows.append(
                    {
                        "case_id": case["id"],
                        "id": alert["id"],
                        "title": alert["title"],
                        "time": _dt(alert["time"]),
                    }
                )
        else:
            raise AssertionError(sql)
    return rows


class FakeDb:
    """read_many를 대신한다. 받은 문장 종류(이름)와 값을 남긴다."""

    NAMES = {
        module.CASES_SQL: "cases",
        module.ARTIFACT_SQL: "artifact",
        module.PROPOSALS_SQL: "proposals",
        module.TICKETS_SQL: "tickets",
        module.ALERTS_SQL: "alerts",
    }

    def __init__(self, mutate: Any = None) -> None:
        self.calls: list[tuple[str, tuple]] = []
        self.batches = 0
        self.mutate = mutate  # (이름, 행 목록) -> 행 목록. 테스트가 행을 바꿀 때 쓴다

    def __call__(self, ctx: Any, queries: list) -> list[list[dict[str, Any]]]:
        self.batches += 1
        out = []
        for sql, params in queries:
            name = self.NAMES[sql]  # 모르는 문장이면 KeyError로 실패한다
            self.calls.append((name, tuple(params)))
            rows = rows_for(sql, tuple(params))
            out.append(self.mutate(name, rows) if self.mutate else rows)
        return out
