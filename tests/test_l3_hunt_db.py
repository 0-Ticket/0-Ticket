"""L3 가설 헌팅의 저장 규칙과 상태 전이를 실제 PostgreSQL로 확인한다(#223, db 마커).

실행 함수는 두 가지를 넣는다. 가짜 실행 결과(AgentResult를 바로 돌려줌)는 상태 전이·Ticket을,
run_task + 가짜 모델 + 가짜 도구(레지스트리, #211)는 Agent Log·data 주입·근거 장부를 거친
종단 흐름을 확인한다.
"""

import copy
import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest
from fake_model import FakeModel
from psycopg import sql
from psycopg.types.json import Jsonb
from tool_helpers import parse

from soc.agent import AgentResult, AgentTask
from soc.agent.agent_log import MemoryLogSink
from soc.agent.config import load_config as load_agent_config
from soc.agent.runner import run_task
from soc.contracts import to_datetime, validate_contract
from soc.db.migrate import migrate
from soc.ids import new_id
from soc.l3.config import load_config
from soc.l3.hunt import store
from soc.l3.hunt.command import run_hunt
from soc.l3.hunt.hypothesize import hypothesize
from soc.l3.hunt.settings import HuntSettings, read_hunt_settings
from soc.l3.hunt.verify import HuntVerifier
from soc.tools import Arg, ToolRegistry, ToolSpec

pytestmark = pytest.mark.db

FIXTURES = Path(__file__).parent / "fixtures" / "l3_hunt"
SEED = json.loads((FIXTURES / "seed.json").read_text(encoding="utf-8"))
NOW_MS = SEED["now"]
NOW = to_datetime(NOW_MS)
DAY_MS = 86_400_000

ALT_1 = SEED["alerts"][0]["id"]
EVT_1 = SEED["events"][0]["id"]
CAS_1, CAS_2 = (c["id"] for c in SEED["cases"])
ALERT_ENTITIES = SEED["alerts"][0]["entities"]
EVENT_ENTITIES = SEED["events"][0]["entities"]
IP_SRC = {"type": "ip", "value": "203.0.113.10", "role": "src"}
IP_DST = {"type": "ip", "value": "203.0.113.10", "role": "dst"}

TIMES = {"fetched_at", "time", "created_at", "updated_at", "confirmed_at", "resolved_at"}
TIMES |= {"published_at"}
JSONB = {"original", "entities", "assets", "triage", "ocsf", "details"}
SEED_TABLES = (
    "raw_records",
    "alerts",
    "events",
    "incidents",
    "cases",
    "threat_news",
    "attack_techniques",
)


def insert_row(conn: psycopg.Connection, table: str, row: dict[str, Any]) -> None:
    values = []
    for key, value in row.items():
        if value is not None and key in TIMES:
            value = to_datetime(value)
        elif value is not None and key in JSONB:
            value = Jsonb(value)
        values.append(value)
    # threat_news.id는 GENERATED ALWAYS라 샘플의 고정 id를 넣으려면 OVERRIDING이 필요하다
    overriding = sql.SQL("OVERRIDING SYSTEM VALUE" if table == "threat_news" else "")
    conn.execute(
        sql.SQL("INSERT INTO {} ({}) {} VALUES ({})").format(
            sql.Identifier(table),
            sql.SQL(", ").join(map(sql.Identifier, row)),
            overriding,
            sql.SQL(", ").join(sql.Placeholder() * len(row)),
        ),
        values,
    )


@pytest.fixture
def db(temp_database: str) -> str:
    migrate(temp_database)
    with psycopg.connect(temp_database, autocommit=True) as conn:
        for table in SEED_TABLES:
            for row in SEED[table]:
                insert_row(conn, table, row)
    return temp_database


@pytest.fixture
def conn(db: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(db, autocommit=True) as connection:
        yield connection


def settings(**hunt: Any) -> HuntSettings:
    l3 = load_config()["l3"]
    return read_hunt_settings({**l3, "hunt": {**l3["hunt"], **hunt}})


class FakeRun:
    """실행 함수 대신 넣는다. 받은 작업을 tasks에 남기고 results를 앞에서부터 돌려준다."""

    def __init__(self, *results: AgentResult | Callable[[AgentTask], AgentResult]) -> None:
        self.results = list(results)
        self.tasks: list[AgentTask] = []

    def __call__(self, task: AgentTask) -> AgentResult:
        self.tasks.append(task)
        if not self.results:
            raise AssertionError("준비한 실행 결과를 다 썼는데 또 불렸다")
        result = self.results.pop(0)
        return result(task) if callable(result) else result


def ok(output: dict[str, Any]) -> AgentResult:
    return AgentResult(
        ok=True,
        output=output,
        failure=None,
        detail=None,
        run_id=new_id("run"),
        cited_evidence_ids=list(output.get("evidence_ids", [])),
    )


def failed(failure: str) -> AgentResult:
    return AgentResult(ok=False, output=None, failure=failure, detail="실패", run_id=new_id("run"))  # type: ignore[arg-type]


def scenario(name: str) -> dict[str, Any]:
    return json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def hypotheses_output() -> dict[str, Any]:
    return scenario("hypothesize_ok")["steps"][0]["final"]


def verification(result: str, confidence: float, evidence: list[str], **extra: Any) -> dict:
    return {
        "result": result,
        "confidence": confidence,
        "reason": "근거를 확인했다",
        "evidence_ids": evidence,
        "entities": [],
        **extra,
    }


def _query_events(args: dict[str, Any], ctx: Any) -> list[dict[str, Any]]:
    return [{"id": ALT_1, "title": "Web Shell Upload"}]


# 테스트용 가짜 도구. records 결과의 id(alt_)와 호출 기록(agl_)이 근거 장부에 들어간다(#211)
QUERY_EVENTS = ToolSpec(
    name="query_events",
    description="엔티티로 Alert·Event를 찾는다(테스트용).",
    handler=_query_events,
    bundle="test",
    result_kind="records",
    id_fields=("id",),
    args=(Arg("entity", "string", required=True),),
)
CALL_ID = "<call_id>"  # 시나리오 파일의 자리표시. 실행 중 도구 결과의 call_id(agl_)로 바꾼다


def with_call_ids(data: dict[str, Any]) -> dict[str, Any]:
    """final의 evidence_ids에 든 자리표시를 첫 도구 결과의 call_id로 바꾸는 final_fn step으로."""
    steps = []
    for step in data["steps"]:
        final = step.get("final")
        if final is None or CALL_ID not in final.get("evidence_ids", []):
            steps.append(step)
            continue

        def cite(outputs: list[str], final: dict[str, Any] = final) -> dict[str, Any]:
            call_id = parse(outputs[0])["call_id"]
            evidence = [call_id if i == CALL_ID else i for i in final["evidence_ids"]]
            return {**final, "evidence_ids": evidence}

        steps.append({"final_fn": cite})
    return {**data, "steps": steps}


def via_run_task(name: str, sink: MemoryLogSink) -> tuple[Callable[[AgentTask], Any], FakeModel]:
    model = FakeModel(with_call_ids(scenario(name)))
    config = copy.deepcopy(load_agent_config())
    config["tools"]["allowed"]["l3"] = [QUERY_EVENTS.name]

    def run(task: AgentTask) -> AgentResult:
        return run_task(
            task,
            model=model,
            model_name="fake-model",
            log_sink=sink,
            config=config,
            registry=ToolRegistry([QUERY_EVENTS]),
        )

    return run, model


def add_hunt(
    conn: psycopg.Connection,
    *,
    techniques: list[str] | None = None,
    created_at: int = NOW_MS - DAY_MS,
    attempts: int = 0,
) -> str:
    hunt = {
        "id": new_id("hnt"),
        "hunt_run_id": new_id("hrn"),
        "status": "pending",
        "hypothesis": "공개 웹 서버의 업로드 기능으로 웹셸이 올라왔다",
        "attack_techniques": techniques if techniques is not None else ["T1190"],
        "confidence": None,
        "reason": None,
        "evidence_ids": [],
        "entities": [],
        "attempts": attempts,
        "verified_at": None,
        "created_at": created_at,
        "updated_at": created_at,
        "details": {},
    }
    validate_contract("hunt", hunt)
    with conn.transaction():
        store.insert_hunts(conn, [hunt])
    return hunt["id"]


def verifier(db: str, run: Callable[[AgentTask], AgentResult], **hunt: Any) -> HuntVerifier:
    return HuntVerifier(db, settings(**hunt), run=run, clock=lambda: NOW)


def tickets_of(conn: psycopg.Connection, hunt_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT id, origin, status, alert_ids, hunt_id, entities, verdict, details"
        " FROM tickets WHERE hunt_id = %s",
        (hunt_id,),
    ).fetchall()
    keys = ("id", "origin", "status", "alert_ids", "hunt_id", "entities", "verdict", "details")
    return [dict(zip(keys, row, strict=True)) for row in rows]


# 가설 생성


def test_hypothesize_saves_pending_hunts_with_news_snapshot(conn: psycopg.Connection) -> None:
    run = FakeRun(ok(hypotheses_output()))

    result = hypothesize(conn, settings(max_hypotheses=2), run=run, now=NOW)

    assert result.failure is None
    assert (len(result.saved), result.unknown_technique, result.over_limit) == (1, 1, 1)
    assert result.dropped_refs == 2  # 입력에 없던 뉴스 99, Case cas_…999
    hunt = store.read_hunt(conn, result.saved[0])
    assert hunt is not None
    validate_contract("hunt", hunt)
    assert hunt["status"] == "pending"
    assert hunt["attempts"] == 0
    assert hunt["hunt_run_id"] == result.hunt_run_id
    assert hunt["attack_techniques"] == ["T1190", "T1505.003"]
    assert (hunt["evidence_ids"], hunt["entities"]) == ([], [])
    news = SEED["threat_news"][0]
    assert hunt["details"]["sources"] == {
        "news": [
            {
                "id": 1,
                "source": news["source"],
                "title": news["title"],
                "summary": news["summary"],
                "published_at": news["published_at"],
            }
        ],
        "case_ids": [CAS_1],
    }


def test_hypothesize_task_reads_recent_news_and_cases(conn: psycopg.Connection) -> None:
    run = FakeRun(ok({"hypotheses": []}))

    result = hypothesize(conn, settings(max_hypotheses=2), run=run, now=NOW)

    (task,) = run.tasks
    assert task.stage == "l3"
    assert task.task == "l3_hypothesize"
    assert task.output_contract == "hunt_hypotheses"
    assert task.subject_type == "hunt"
    assert task.subject_id == result.hunt_run_id
    assert task.subject_id.startswith("hrn_")
    assert task.allowed_evidence_ids == ()
    assert list(task.cited_ids(hypotheses_output())) == []
    # 기간 안의 뉴스만, COALESCE(published_at, fetched_at) 내림차순. 3번은 published_at이 null이다
    assert [n["id"] for n in task.data["news"]] == [1, 3, 2]
    assert task.data["news"][1]["published_at"] is None
    assert [c["id"] for c in task.data["cases"]] == [CAS_1, CAS_2]
    assert set(task.data["cases"][0]) == {"id", "title", "summary", "severity", "entities"}
    assert task.data["max_hypotheses"] == 2
    assert result.saved == []


def test_hypothesize_respects_news_and_case_limits(conn: psycopg.Connection) -> None:
    run = FakeRun(ok({"hypotheses": []}))

    hypothesize(conn, settings(news_limit=2, case_limit=1), run=run, now=NOW)

    assert [n["id"] for n in run.tasks[0].data["news"]] == [1, 3]
    assert [c["id"] for c in run.tasks[0].data["cases"]] == [CAS_1]


def test_unknown_technique_hypothesis_is_not_saved(conn: psycopg.Connection) -> None:
    run = FakeRun(ok(hypotheses_output()))

    result = hypothesize(conn, settings(max_hypotheses=3), run=run, now=NOW)

    assert (len(result.saved), result.unknown_technique, result.over_limit) == (2, 1, 0)
    saved = [store.read_hunt(conn, i) for i in result.saved]
    assert [h["attack_techniques"] for h in saved if h] == [["T1190", "T1505.003"], ["T1059.004"]]
    count = conn.execute("SELECT count(*) FROM hunts WHERE 'T9999' = ANY(attack_techniques)")
    assert count.fetchone() == (0,)


def test_hypothesize_is_skipped_without_attack_version(conn: psycopg.Connection) -> None:
    conn.execute("DELETE FROM attack_techniques")
    run = FakeRun()

    result = hypothesize(conn, settings(), run=run, now=NOW)

    assert result.skipped == "no_attack_version"
    assert run.tasks == []


def test_failed_hypothesize_saves_no_hunt(conn: psycopg.Connection) -> None:
    result = hypothesize(conn, settings(), run=FakeRun(failed("format_error")), now=NOW)

    assert result.failure == "format_error"
    assert result.saved == []
    assert conn.execute("SELECT count(*) FROM hunts").fetchone() == (0,)


def test_hypothesize_via_run_task_keeps_news_in_data_and_logs_hunt_run(
    conn: psycopg.Connection,
) -> None:
    sink = MemoryLogSink()
    run, model = via_run_task("hypothesize_ok", sink)

    result = hypothesize(conn, settings(max_hypotheses=2), run=run, now=NOW)

    assert result.failure is None
    assert len(result.saved) == 1
    (call,) = model.calls
    assert "INJECTED-INSTRUCTION" not in call["system"]
    (message,) = call["input"]
    assert message["content"].startswith("<data>\n")
    assert "INJECTED-INSTRUCTION" in message["content"]
    assert sink.rows
    assert {(r["subject_type"], r["subject_id"]) for r in sink.rows} == {
        ("hunt", result.hunt_run_id)
    }


# 검증


def test_confirmed_hunt_creates_l3_ticket(db: str, conn: psycopg.Connection) -> None:
    hunt_id = add_hunt(conn, techniques=["T1190", "T1505.003"])
    output = verification("confirmed", 0.9, [EVT_1, ALT_1], entities=[IP_SRC, IP_DST])
    run = FakeRun(ok(output))

    verifier(db, run).handle(hunt_id)

    hunt = store.read_hunt(conn, hunt_id)
    assert hunt is not None
    validate_contract("hunt", hunt)
    assert hunt["status"] == "confirmed"
    assert hunt["attempts"] == 1
    assert (hunt["confidence"], hunt["reason"]) == (0.9, "근거를 확인했다")
    assert hunt["evidence_ids"] == [EVT_1, ALT_1]
    assert hunt["verified_at"] == NOW_MS
    assert hunt["entities"] == [*EVENT_ENTITIES, *ALERT_ENTITIES[1:], IP_DST]
    assert hunt["details"]["model_only_entities"] == [IP_DST]
    assert hunt["details"]["missing_evidence_rows"] == 0
    (ticket,) = tickets_of(conn, hunt_id)
    assert ticket["origin"] == "l3"
    assert ticket["status"] == "escalated"
    assert ticket["alert_ids"] == []
    assert ticket["verdict"] is None
    assert ticket["entities"] == hunt["entities"]
    assert ticket["id"].startswith("tkt_")


def test_verify_task_has_hypothesis_techniques_and_window(
    db: str, conn: psycopg.Connection
) -> None:
    hunt_id = add_hunt(conn, techniques=["T1190", "T1505.003"])
    run = FakeRun(ok(verification("inconclusive", 0.3, [])))

    verifier(db, run).handle(hunt_id)

    (task,) = run.tasks
    assert task.stage == "l3"
    assert task.task == "l3_verify"
    assert task.output_contract == "hunt_verification"
    assert (task.subject_type, task.subject_id) == ("hunt", hunt_id)
    assert task.attempt == 1
    assert task.data == {
        "hypothesis": "공개 웹 서버의 업로드 기능으로 웹셸이 올라왔다",
        "attack_techniques": [
            {"id": "T1190", "name": "Exploit Public-Facing Application"},
            {"id": "T1505.003", "name": "Web Shell"},
        ],
        "window": {"from": NOW_MS - 7 * DAY_MS, "to": NOW_MS},
    }
    assert list(task.cited_ids(verification("rejected", 0.8, [ALT_1]))) == [ALT_1]


@pytest.mark.parametrize(
    "output",
    [verification("rejected", 0.8, [EVT_1]), verification("inconclusive", 0.4, [])],
    ids=["rejected", "inconclusive"],
)
def test_rejected_and_inconclusive_make_no_ticket(
    db: str, conn: psycopg.Connection, output: dict[str, Any]
) -> None:
    hunt_id = add_hunt(conn)

    verifier(db, FakeRun(ok(output))).handle(hunt_id)

    hunt = store.read_hunt(conn, hunt_id)
    assert hunt is not None
    assert hunt["status"] == output["result"]
    assert "downgraded" not in hunt["details"]
    assert tickets_of(conn, hunt_id) == []


@pytest.mark.parametrize(
    ("output", "rules"),
    [
        (verification("confirmed", 0.5, [ALT_1]), ["threshold"]),
        (verification("confirmed", 0.9, ["agl_01a19f93-1150-7000-8000-000000000001"]), None),
        (verification("rejected", 0.8, []), ["no_evidence"]),
    ],
    ids=["below_threshold", "no_record_evidence", "rejected_without_evidence"],
)
def test_ungrounded_results_are_saved_as_inconclusive(
    db: str, conn: psycopg.Connection, output: dict[str, Any], rules: list[str] | None
) -> None:
    hunt_id = add_hunt(conn)

    verifier(db, FakeRun(ok(output))).handle(hunt_id)

    hunt = store.read_hunt(conn, hunt_id)
    assert hunt is not None
    validate_contract("hunt", hunt)
    assert hunt["status"] == "inconclusive"
    assert hunt["details"]["downgraded"] == {
        "from": output["result"],
        "rules": rules or ["no_record_evidence"],
    }
    assert tickets_of(conn, hunt_id) == []


def test_missing_evidence_rows_are_counted(db: str, conn: psycopg.Connection) -> None:
    hunt_id = add_hunt(conn)
    unknown = "alt_01a19f93-1150-7000-8000-0000000000ff"
    run = FakeRun(ok(verification("confirmed", 0.9, [unknown, EVT_1])))

    verifier(db, run).handle(hunt_id)

    hunt = store.read_hunt(conn, hunt_id)
    assert hunt is not None
    assert hunt["entities"] == EVENT_ENTITIES
    assert hunt["details"]["missing_evidence_rows"] == 1


def test_failed_runs_retry_then_fail(db: str, conn: psycopg.Connection) -> None:
    hunt_id = add_hunt(conn)
    run = FakeRun(failed("provider_error"), failed("log_error"))
    worker = verifier(db, run)

    worker.handle(hunt_id)
    first = store.read_hunt(conn, hunt_id)
    worker.handle(hunt_id)
    second = store.read_hunt(conn, hunt_id)
    worker.handle(hunt_id)  # failed는 다시 실행하지 않는다

    assert first is not None and second is not None
    assert (first["status"], first["attempts"]) == ("pending", 1)
    assert [f["failure"] for f in first["details"]["verify_failures"]] == ["provider_error"]
    assert (second["status"], second["attempts"]) == ("failed", 2)
    validate_contract("hunt", second)
    assert (second["confidence"], second["reason"], second["verified_at"]) == (None, None, None)
    failures = second["details"]["verify_failures"]
    assert [(f["attempt"], f["failure"]) for f in failures] == [
        (1, "provider_error"),
        (2, "log_error"),
    ]
    assert all(f["run_id"].startswith("run_") for f in failures)
    assert [t.attempt for t in run.tasks] == [1, 2]


def test_handle_twice_makes_one_ticket(db: str, conn: psycopg.Connection) -> None:
    hunt_id = add_hunt(conn)
    run = FakeRun(ok(verification("confirmed", 0.9, [ALT_1])))
    worker = verifier(db, run)

    worker.handle(hunt_id)
    worker.handle(hunt_id)

    assert len(tickets_of(conn, hunt_id)) == 1
    assert len(run.tasks) == 1


def test_existing_ticket_for_hunt_is_kept(db: str, conn: psycopg.Connection) -> None:
    """다른 실행이 이미 Ticket을 만든 경우: UniqueViolation을 savepoint로 넘기고 Hunt는 저장한다."""
    hunt_id = add_hunt(conn)
    existing = {
        "id": new_id("tkt"),
        "origin": "l3",
        "status": "escalated",
        "alert_ids": [],
        "hunt_id": hunt_id,
        "entities": [],
        "verdict": None,
        "created_at": NOW_MS,
        "updated_at": NOW_MS,
        "details": {},
    }
    validate_contract("ticket", existing)
    with conn.transaction():
        assert store.insert_ticket(conn, existing) is True

    verifier(db, FakeRun(ok(verification("confirmed", 0.9, [ALT_1])))).handle(hunt_id)

    hunt = store.read_hunt(conn, hunt_id)
    assert hunt is not None
    assert hunt["status"] == "confirmed"
    assert [t["id"] for t in tickets_of(conn, hunt_id)] == [existing["id"]]


def test_hunt_changed_during_run_is_not_overwritten(db: str, conn: psycopg.Connection) -> None:
    hunt_id = add_hunt(conn)

    def other_process_finishes_first(task: AgentTask) -> AgentResult:
        conn.execute(
            "UPDATE hunts SET status = 'rejected', attempts = 1, confidence = 0.8, reason = 'x',"
            " evidence_ids = %s, verified_at = now() WHERE id = %s",
            ([EVT_1], hunt_id),
        )
        return ok(verification("confirmed", 0.9, [ALT_1]))

    verifier(db, FakeRun(other_process_finishes_first)).handle(hunt_id)

    hunt = store.read_hunt(conn, hunt_id)
    assert hunt is not None
    assert hunt["status"] == "rejected"
    assert tickets_of(conn, hunt_id) == []


def test_poll_returns_pending_hunts_in_creation_order(db: str, conn: psycopg.Connection) -> None:
    later = add_hunt(conn, created_at=NOW_MS - 1000)
    earlier = add_hunt(conn, created_at=NOW_MS - 5000)
    done = add_hunt(conn, created_at=NOW_MS - 9000)
    verifier(db, FakeRun(ok(verification("rejected", 0.8, [EVT_1])))).handle(done)
    worker = verifier(db, FakeRun())

    assert worker.stage == "l3"
    assert worker.name
    assert worker.poll(10) == [earlier, later]
    assert worker.poll(1) == [earlier]
    assert worker.poll(None) == [earlier, later]


# run_task 경로(가짜 모델·가짜 도구)


def test_verify_via_run_task_logs_hunt_and_accepts_tool_log_evidence(
    db: str, conn: psycopg.Connection
) -> None:
    hunt_id = add_hunt(conn)
    sink = MemoryLogSink()
    run, _ = via_run_task("verify_rejected_tool", sink)

    verifier(db, run).handle(hunt_id)

    hunt = store.read_hunt(conn, hunt_id)
    assert hunt is not None
    assert hunt["status"] == "rejected"
    assert [r["kind"] for r in sink.rows] == ["model", "tool", "model"]
    assert hunt["evidence_ids"] == [sink.rows[1]["id"]]  # 도구 줄 agl_ = 도구 결과의 call_id
    assert {(r["subject_type"], r["subject_id"]) for r in sink.rows} == {("hunt", hunt_id)}


def test_confirmed_with_tool_log_only_via_run_task_is_inconclusive(
    db: str, conn: psycopg.Connection
) -> None:
    hunt_id = add_hunt(conn)
    run, _ = via_run_task("verify_confirmed_tool_only", MemoryLogSink())

    verifier(db, run).handle(hunt_id)

    hunt = store.read_hunt(conn, hunt_id)
    assert hunt is not None
    assert hunt["status"] == "inconclusive"
    assert hunt["details"]["downgraded"] == {"from": "confirmed", "rules": ["no_record_evidence"]}
    assert hunt["entities"] == [IP_SRC]
    assert hunt["details"]["model_only_entities"] == [IP_SRC]
    assert tickets_of(conn, hunt_id) == []


def test_confirmed_with_tool_record_via_run_task_creates_l3_ticket(
    db: str, conn: psycopg.Connection
) -> None:
    """종단: 도구 결과의 alt_가 근거 장부에 들어가(#211) confirmed가 되고 L3 Ticket이 생긴다."""
    hunt_id = add_hunt(conn)
    sink = MemoryLogSink()
    run, _ = via_run_task("verify_confirmed_tool_record", sink)

    verifier(db, run).handle(hunt_id)

    hunt = store.read_hunt(conn, hunt_id)
    assert hunt is not None
    validate_contract("hunt", hunt)
    assert (hunt["status"], hunt["attempts"]) == ("confirmed", 1)
    assert hunt["evidence_ids"] == [ALT_1, sink.rows[1]["id"]]
    assert hunt["entities"] == ALERT_ENTITIES
    (ticket,) = tickets_of(conn, hunt_id)
    assert (ticket["origin"], ticket["status"], ticket["alert_ids"]) == ("l3", "escalated", [])
    assert ticket["entities"] == ALERT_ENTITIES


def test_citing_unseen_alert_via_run_task_is_a_failed_attempt(
    db: str, conn: psycopg.Connection
) -> None:
    """도구 결과에 없던 Alert ID를 인용하면 evidence_id_error이고, 시도 1회로 센다."""
    hunt_id = add_hunt(conn)
    run, _ = via_run_task("verify_cites_unseen_alert", MemoryLogSink())

    verifier(db, run).handle(hunt_id)

    hunt = store.read_hunt(conn, hunt_id)
    assert hunt is not None
    assert (hunt["status"], hunt["attempts"]) == ("pending", 1)
    assert hunt["details"]["verify_failures"][0]["failure"] == "evidence_id_error"
    assert tickets_of(conn, hunt_id) == []


# 명령


class Output:
    def __init__(self) -> None:
        self.out: list[str] = []
        self.err: list[str] = []

    def text(self) -> str:
        return "\n".join(self.out + self.err)


def no_client(*_: Any) -> httpx.Client:
    raise AssertionError("collect_before = false인데 수집을 했다")


def command(db: str | None, run: FakeRun, output: Output, **hunt: Any) -> int:
    l3 = load_config()["l3"]
    l3 = {**l3, "hunt": {**l3["hunt"], "collect_before": False, **hunt}}
    return run_hunt(
        l3,
        db,
        run=run,
        client_factory=no_client,
        clock=lambda: NOW,
        out=output.out.append,
        err=output.err.append,
    )


def one_hypothesis() -> dict[str, Any]:
    return {"hypotheses": hypotheses_output()["hypotheses"][:1]}


def test_command_hypothesizes_verifies_and_prints_counts_only(db: str) -> None:
    run = FakeRun(ok(one_hypothesis()), ok(verification("confirmed", 0.9, [ALT_1])))
    output = Output()

    code = command(db, run, output)

    assert code == 0
    assert [t.task for t in run.tasks] == ["l3_hypothesize", "l3_verify"]
    text = output.text()
    assert "confirmed 1" in text
    assert "웹셸" not in text  # 가설 문장
    assert "근거를 확인했다" not in text  # 이유
    assert "INJECTED" not in text  # 뉴스 제목
    with psycopg.connect(db) as conn:
        assert conn.execute("SELECT count(*) FROM tickets WHERE origin = 'l3'").fetchone() == (1,)


def test_command_verifies_waiting_hunts_even_when_hypothesize_fails(db: str) -> None:
    with psycopg.connect(db, autocommit=True) as conn:
        waiting = add_hunt(conn, attempts=1)
    run = FakeRun(failed("provider_error"), ok(verification("rejected", 0.8, [EVT_1])))
    output = Output()

    code = command(db, run, output)

    assert code == 1
    assert "provider_error" in output.text()
    assert run.tasks[1].subject_id == waiting
    assert run.tasks[1].attempt == 2
    assert "rejected 1" in output.text()


def test_command_collects_first_and_survives_collect_failure(db: str) -> None:
    run = FakeRun(ok({"hypotheses": []}))
    output = Output()
    requested: list[str] = []

    def failing_web(_: Any) -> httpx.Client:
        def handler(request: httpx.Request) -> httpx.Response:
            requested.append(str(request.url))
            return httpx.Response(500)

        return httpx.Client(transport=httpx.MockTransport(handler))

    l3 = load_config()["l3"]
    code = run_hunt(
        {**l3, "hunt": {**l3["hunt"], "collect_before": True}},
        db,
        run=run,
        client_factory=failing_web,
        clock=lambda: NOW,
        out=output.out.append,
        err=output.err.append,
    )

    assert code == 0
    assert requested  # 출처를 가져오려 했다(ATT&CK 20.0은 이미 있어 건너뜀)
    assert "실패 http_status" in output.text()
    assert [t.task for t in run.tasks] == ["l3_hypothesize"]


def test_command_reports_skipped_hypothesize_without_attack(db: str) -> None:
    with psycopg.connect(db, autocommit=True) as conn:
        conn.execute("DELETE FROM attack_techniques")
    output = Output()

    code = command(db, FakeRun(), output)

    assert code == 0
    assert "ATT&CK" in output.text()


def test_command_config_errors_exit_2(db: str) -> None:
    output = Output()

    assert command(db, FakeRun(), output, max_attempts=0) == 2
    assert command(None, FakeRun(), Output()) == 2


def test_command_db_error_exits_1_without_address(db: str) -> None:
    output = Output()
    bad = "postgresql://nobody:s3cret-value@127.0.0.1:1/none"

    code = command(bad, FakeRun(), output)

    assert code == 1
    assert "s3cret-value" not in output.text()
    assert "127.0.0.1" not in output.text()
