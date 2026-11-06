"""랩 ELK 모양으로 파이프 한 바퀴를 확인한다(#264, db 마커).

서버(Azure 랩) 시험 전에 단계 사이의 어긋남을 잡는 것이 목적이다. 판정 품질은 보지 않는다.

- 샘플: tests/fixtures/lab_cycle/의 손으로 만든 ELK 검색 응답. 랩에서 확인한 사실로 만들었다
  (Filebeat가 filebeat-*로 보냄, nginx ECS 필드 4개, Elastic Security 룰 query 9 + threshold 3,
  MITRE는 tags에만). event.dataset 값, 데이터 스트림 _index 모양, threshold 알럿 문서 모양은
  가정이다(docs/notes/264-lab-cycle.md).
- 흐름: 가짜 ELK → 수집 → 정규화 → Ticket(auto) → L1(가짜 모델로 run_agent, get_alert 도구) →
  L2 분류(가짜 임베더·메모리 벡터 저장소, recent) → L2 분석(가짜 실행) → Incident Artifact.
- 시각은 모두 고정한 NOW로 준다(시간 창 비교가 실행 날짜에 따라 달라지지 않게).
"""

import json
import secrets
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest
from conftest import HiddenUrl
from fake_elk import FakeElk, make_settings, respond
from fake_embedder import FakeEmbedder
from fake_model import FakeModel
from psycopg import sql
from psycopg.conninfo import make_conninfo
from psycopg.rows import dict_row
from test_agent_core import CONFIG, no_sleep
from tool_helpers import parse

from soc.agent import AgentResult, AgentTask
from soc.agent.agent_log import PostgresLogSink
from soc.agent.runner import run_task
from soc.contracts import to_datetime, validate_contract
from soc.db.migrate import migrate
from soc.ids import new_id
from soc.ingest.config import Source
from soc.ingest.run import run as ingest_run
from soc.l1.judge import L1Worker
from soc.l1.ticketing import run as ticketing_run
from soc.l2.analyze.worker import L2AnalyzeWorker
from soc.l2.branch.worker import L2BranchWorker
from soc.l2.config import AnalyzeSettings, BranchSettings
from soc.l3.config import load_config as load_l3_config
from soc.l3.hunt import store as hunt_store
from soc.l3.hunt.settings import read_hunt_settings
from soc.l3.hunt.verify import HuntVerifier
from soc.normalize.config import Settings as NormalizeSettings
from soc.normalize.run import run as normalize_run
from soc.ticketing import TicketingPolicy
from soc.tools import default_registry

pytestmark = pytest.mark.db

FIXTURES = Path(__file__).parent / "fixtures" / "lab_cycle"
NOW_MS = 1_793_847_600_000  # 2026-11-05T03:00:00Z. 샘플 알럿·이벤트보다 1시간쯤 뒤
NOW = to_datetime(NOW_MS)
ATTACK_MS = 1_793_844_000_000  # 2026-11-05T02:00:00Z. 샘플의 첫 공격 요청 시각

ALERT_SOURCE = Source(kind="alert", key=".alerts-security.alerts-default", time_field="@timestamp")
EVENT_SOURCE = Source(kind="event", key="filebeat-*", time_field="@timestamp")
NORMALIZE = NormalizeSettings(
    batch_size=200, lease_seconds=600, connect_timeout_seconds=5, asset_statement_timeout_ms=5000
)
AUTO = TicketingPolicy(mode="auto", scenario_rule_ids=())
BRANCH = BranchSettings(
    candidate_window_ms=86_400_000, max_candidates=5, candidate_source="recent", top_k=50
)
ANALYZE = AnalyzeSettings(
    lookback_ms=86_400_000, max_analysis_rounds=5, max_seed_entities=10, max_related_per_entity=20
)
L1_CONFIG = {**CONFIG, "tools": {**CONFIG["tools"], "allowed": {"l1": ["get_alert"]}}}
READER = "soc_agent_reader"

QUERY_RULE = "Lab web SQL injection attempt"
LOGIN_RULE = "Lab login brute force"
WAF_RULE = "Lab WAF repeated block"


def search_response(name: str) -> httpx.Response:
    """tests/fixtures/lab_cycle/의 검색 응답 하나. 인자 name은 파일 이름이다."""
    return respond(200, json.loads((FIXTURES / name).read_text(encoding="utf-8")))


class MemoryVectorStore:
    """L2 분류 워커의 벡터 저장소 대역. recent 경로라 upsert만 받는다."""

    def __init__(self) -> None:
        self.upserts: list[tuple[str, list[float], dict[str, str]]] = []

    def upsert(self, point_id: str, vector: list[float], payload: dict[str, str]) -> None:
        self.upserts.append((point_id, vector, payload))


def ok(output: dict[str, Any]) -> AgentResult:
    """가짜 실행이 돌려줄 성공 결과. 인자 output은 계약 모양의 출력이다."""
    return AgentResult(
        ok=True,
        output=output,
        failure=None,
        detail=None,
        run_id=new_id("run"),
        cited_evidence_ids=list(output.get("evidence_ids", [])),
    )


@pytest.fixture
def db(temp_database: HiddenUrl) -> HiddenUrl:
    migrate(temp_database)
    return temp_database


@pytest.fixture
def conn(db: HiddenUrl) -> Iterator[psycopg.Connection]:
    # 단계 코드에 넘기는 연결이라 기본(튜플) 행으로 둔다. 확인 쿼리는 q()로 dict 행을 읽는다.
    with psycopg.connect(db, autocommit=True) as connection:
        yield connection


@pytest.fixture
def reader_url(db: HiddenUrl, monkeypatch: pytest.MonkeyPatch) -> Iterator[HiddenUrl]:
    """L1 도구(get_alert)가 접속할 soc_agent_reader 멤버 임시 LOGIN 역할. 끝나면 지운다."""
    name = f"soc_test_reader_{secrets.token_hex(4)}"
    password = secrets.token_urlsafe(16)
    with psycopg.connect(db, autocommit=True) as admin:
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE {}").format(
                sql.Identifier(name), sql.Literal(password), sql.Identifier(READER)
            )
        )
    url = HiddenUrl(make_conninfo(db, user=name, password=password))
    monkeypatch.setenv("AGENT_DATABASE_URL", url)
    try:
        yield url
    finally:
        with psycopg.connect(db, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(name)))


def q(conn: psycopg.Connection, query: str, params: tuple[Any, ...] = ()) -> psycopg.Cursor:
    """확인용 쿼리를 dict 행 커서로 실행한다. query는 이 파일의 상수 문장이다."""
    return conn.cursor(row_factory=dict_row).execute(query, params)


# 단계


def ingest_once(conn: psycopg.Connection) -> list[Any]:
    """가짜 ELK로 수집을 한 번 돌린다. 두 번째 실행에도 같은 문서를 다시 돌려준다(겹침 재현)."""
    fake = FakeElk(
        {
            ALERT_SOURCE.key: [search_response("alerts.json")],
            EVENT_SOURCE.key: [search_response("events.json")],
        }
    )
    settings = make_settings(ALERT_SOURCE, EVENT_SOURCE, page_size=500)
    with fake.client() as client:
        return ingest_run(settings, conn, client)


def l1_run(db: str) -> Any:
    """L1 실행 함수. 작업마다 가짜 모델이 get_alert로 첫 Alert를 읽고 malicious로 판정한다."""

    def run(task: AgentTask) -> AgentResult:
        alert_id = task.allowed_evidence_ids[0]

        def cite(outputs: list[str]) -> dict[str, Any]:
            return {
                "decision": "malicious",
                "confidence": 0.9,
                "reason": "도구로 읽은 Alert가 웹 공격 룰과 맞다",
                "evidence_ids": [alert_id, parse(outputs[0])["call_id"]],
                "decided_at": NOW_MS,
            }

        model = FakeModel(
            {
                "steps": [
                    {"tool_call": {"name": "get_alert", "arguments": {"id": alert_id}}},
                    {"final_fn": cite},
                ]
            }
        )
        return run_task(
            task,
            model=model,
            model_name="fake-model",
            log_sink=PostgresLogSink(db),
            config=L1_CONFIG,
            registry=default_registry(),
            sleep=no_sleep,
        )

    return run


def branch_run(task: AgentTask) -> AgentResult:
    """L2 분류 실행 함수. 후보가 있으면 첫 후보 Incident를 고른다."""
    return ok(
        {
            "decision": "existing",
            "incident_id": task.data["candidates"][0]["incident_id"],
            "confidence": 0.9,
            "reason": "같은 웹 서버를 노린 공격이다",
            "similar_ticket_ids": [],
        }
    )


def analyze_run(task: AgentTask) -> AgentResult:
    """L2 분석 실행 함수. 조사와 보고서 모두 허용된 Alert 하나를 근거로 든다."""
    alert_id = next(i for i in task.allowed_evidence_ids if i.startswith("alt_"))
    if task.task == "l2_investigate":
        timeline = [
            {
                "time": ATTACK_MS,
                "summary": "게시판에 SQL 주입 요청이 들어왔다",
                "evidence_ids": [alert_id],
            }
        ]
        return ok({"timeline": timeline, "entities": [], "evidence_ids": [alert_id]})
    return ok(
        {
            "verdict": "attempted",
            "summary": "웹 게시판을 노린 공격 시도가 있었다",
            "assessed_severity": 4,
            "techniques": [],
            "impact": "확인된 피해 없음",
            "cause": "공개 웹 게시판",
            "further_risk": "같은 출발지의 반복 시도",
            "detection_rules": ["같은 출발지의 반복 차단을 탐지한다"],
            "response_actions": ["담당자가 출발지 차단 여부를 검토한다"],
            "evidence_ids": [alert_id],
        }
    )


def branch_worker(db: str, store: MemoryVectorStore) -> L2BranchWorker:
    return L2BranchWorker(db, BRANCH, FakeEmbedder(), store, run=branch_run, clock=lambda: NOW)


def drain(worker: Any) -> int:
    """worker가 poll로 받은 대상을 모두 handle한다. 처리한 수를 돌려준다."""
    ids = worker.poll(100)
    for subject_id in ids:
        worker.handle(subject_id)
    return len(ids)


def counts(conn: psycopg.Connection) -> dict[str, int]:
    tables = ("raw_records", "alerts", "events", "tickets", "incidents", "incident_artifacts")
    return {t: q(conn, f"SELECT count(*) AS n FROM {t}").fetchone()["n"] for t in tables}


def alert_by_title(conn: psycopg.Connection, title: str) -> dict[str, Any]:
    return q(conn, "SELECT * FROM alerts WHERE title = %s", (title,)).fetchone()


# 테스트


def test_lab_shaped_alert_flows_to_incident_artifact_and_rerun_adds_nothing(
    db: HiddenUrl, conn: psycopg.Connection, reader_url: HiddenUrl
) -> None:
    # 1 수집: 알럿 alias와 filebeat-*
    results = ingest_once(conn)
    assert [(r.name, r.inserted, r.failure) for r in results] == [
        ("alert:.alerts-security.alerts-default", 4, None),
        ("event:filebeat-*", 5, None),
    ]
    outcomes = q(conn, "SELECT outcome FROM ingest_runs ORDER BY id").fetchall()
    assert [row["outcome"] for row in outcomes] == ["ok", "ok"]

    # 2 정규화: 실패 0건
    normalized = normalize_run(NORMALIZE, conn, "lab-cycle")
    assert (normalized.succeeded, normalized.failed, normalized.failures) == (9, 0, {})
    classes = q(conn, "SELECT ocsf_class, count(*) AS n FROM events GROUP BY ocsf_class").fetchall()
    # 알려진 문제(docs/notes/264-lab-cycle.md "발견한 문제"): 정규화는 _index 이름으로만 웹 접근
    # 로그를 가려, filebeat-*(.ds-filebeat-…)의 nginx 로그는 HTTP Activity(4002)가 아니라
    # Base Event(0)가 된다. 정규화를 고치면 이 단언을 바꾼다.
    assert {row["ocsf_class"]: row["n"] for row in classes} == {0: 5}

    query_alert = alert_by_title(conn, QUERY_RULE)
    assert query_alert["rule_id"] == "lab-rule-web-sqli"
    assert {"type": "ip", "value": "203.0.113.10", "role": "src"} in query_alert["entities"]
    # threshold 알럿에 original_time이 없으면 @timestamp(02:03)를 쓴다
    login_alert = alert_by_title(conn, LOGIN_RULE)
    assert login_alert["time"] == to_datetime(1_793_844_180_000)
    # WAF 반복차단: 묶음 필드가 transaction.client_ip뿐이라 ip Entity가 없다(발견한 문제)
    waf_alert = alert_by_title(conn, WAF_RULE)
    assert [e for e in waf_alert["entities"] if e["type"] == "ip"] == []

    # 3 Ticket(auto): Alert 4건 → Ticket(new) 4건
    ticketed = ticketing_run(conn, AUTO, clock=lambda: NOW_MS)
    assert (ticketed.candidates, ticketed.created, ticketed.failed) == (4, 4, 0)

    # 4 L1: 가짜 모델이 get_alert로 읽고 판정 → escalated
    l1 = L1Worker(db, 0.8, run=l1_run(db), clock=lambda: NOW)
    assert drain(l1) == 4
    statuses = q(conn, "SELECT status, count(*) AS n FROM tickets GROUP BY status").fetchall()
    assert {row["status"]: row["n"] for row in statuses} == {"escalated": 4}
    tool_rows = q(
        conn,
        "SELECT count(*) AS n FROM agent_logs WHERE kind = 'tool' AND stage = 'l1'"
        " AND name = 'get_alert' AND outcome = 'ok'",
    ).fetchone()
    assert tool_rows["n"] == 4

    # 5 L2 분류: 첫 Ticket이 새 Incident, 나머지는 그 Incident를 고른다
    vectors = MemoryVectorStore()
    assert drain(branch_worker(db, vectors)) == 4
    incidents = q(conn, "SELECT * FROM incidents").fetchall()
    assert len(incidents) == 1 and len(incidents[0]["ticket_ids"]) == 4
    assert incidents[0]["status"] == "analyzing"
    assert len(vectors.upserts) == 4

    # 6 L2 분석: Artifact 한 행, 사람 검토 대기
    analyzer = L2AnalyzeWorker(
        db,
        ANALYZE,
        max_range_days=7,
        asset_statement_timeout_ms=5000,
        attack_version="20.0",
        run=analyze_run,
        clock=lambda: NOW,
    )
    assert drain(analyzer) == 1
    incident = q(conn, "SELECT * FROM incidents").fetchone()
    assert incident["status"] == "awaiting_review"
    artifacts = q(conn, "SELECT * FROM incident_artifacts").fetchall()
    assert len(artifacts) == 1 and artifacts[0]["verdict"] == "attempted"

    first = counts(conn)
    assert first == {
        "raw_records": 9,
        "alerts": 4,
        "events": 5,
        "tickets": 4,
        "incidents": 1,
        "incident_artifacts": 1,
    }

    # 2회차: 같은 명령을 다시 돌려도 늘지 않는다
    again = ingest_once(conn)
    assert [(r.inserted, r.failure) for r in again] == [(0, None), (0, None)]
    assert normalize_run(NORMALIZE, conn, "lab-cycle").claimed == 0
    assert ticketing_run(conn, AUTO, clock=lambda: NOW_MS).created == 0
    assert drain(L1Worker(db, 0.8, run=l1_run(db), clock=lambda: NOW)) == 0
    assert drain(branch_worker(db, vectors)) == 0
    assert drain(analyzer) == 0
    assert counts(conn) == first


def test_l3_ticket_from_lab_records_enters_l2_branch(
    db: HiddenUrl, conn: psycopg.Connection, default_config_dir: Path
) -> None:
    ingest_once(conn)
    normalize_run(NORMALIZE, conn, "lab-cycle")
    query_alert = alert_by_title(conn, QUERY_RULE)

    hunt = {
        "id": new_id("hnt"),
        "hunt_run_id": new_id("hrn"),
        "status": "pending",
        "hypothesis": "공개 웹 게시판의 입력 값으로 SQL 주입을 시도했다",
        "attack_techniques": ["T1190"],
        "confidence": None,
        "reason": None,
        "evidence_ids": [],
        "entities": [],
        "attempts": 0,
        "verified_at": None,
        "created_at": NOW_MS - 3_600_000,
        "updated_at": NOW_MS - 3_600_000,
        "details": {},
    }
    validate_contract("hunt", hunt)
    with conn.transaction():
        hunt_store.insert_hunts(conn, [hunt])

    verification = {
        "result": "confirmed",
        "confidence": 0.9,
        "reason": "같은 출발지의 SQL 주입 알럿이 있다",
        "evidence_ids": [query_alert["id"]],
        "entities": [],
    }
    settings = read_hunt_settings(load_l3_config(default_config_dir)["l3"])
    HuntVerifier(db, settings, run=lambda task: ok(verification), clock=lambda: NOW).handle(
        hunt["id"]
    )
    ticket = q(conn, "SELECT * FROM tickets WHERE hunt_id = %s", (hunt["id"],)).fetchone()
    assert (ticket["origin"], ticket["status"]) == ("l3", "escalated")

    vectors = MemoryVectorStore()
    assert drain(branch_worker(db, vectors)) == 1
    ticket = q(conn, "SELECT * FROM tickets WHERE id = %s", (ticket["id"],)).fetchone()
    assert ticket["status"] == "linked"
    incident = q(conn, "SELECT * FROM incidents").fetchone()
    assert incident["ticket_ids"] == [ticket["id"]]
    assert incident["status"] == "analyzing"
