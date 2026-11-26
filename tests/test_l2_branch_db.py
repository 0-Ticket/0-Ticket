"""L2 분류 입력을 PostgreSQL에서 읽는 경계를 확인한다(db 마커)."""

import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

from soc.agent import AgentResult
from soc.agent.compose import compose_instructions
from soc.agent.llm import input_chars
from soc.agent.runner import wrap_data
from soc.asset_lookup import AssetLookupError
from soc.contracts import to_datetime, validate_contract
from soc.db.migrate import MIGRATIONS_DIR, migrate
from soc.ids import new_id
from soc.l2.analyze import context as analyze_context
from soc.l2.analyze.tasks import make_investigate_task
from soc.l2.analyze.worker import L2AnalyzeWorker
from soc.l2.branch import build_branch
from soc.l2.branch.candidates import find_candidates, index_ready
from soc.l2.branch.embed import embedding_text
from soc.l2.branch.index import check, index_one, reindex, resume
from soc.l2.branch.outbox import enqueue
from soc.l2.branch.read import read_branch_data
from soc.l2.branch.runtime import BranchService
from soc.l2.branch.worker import L2BranchWorker
from soc.l2.config import AnalyzeSettings, BranchSettings
from soc.store import VectorStore
from soc.store.config import load_config as load_store_config
from soc.store.config import read_settings as read_store_settings
from soc.store.qdrant import SearchHit
from soc.ticketing import FALLBACK_TITLE

pytestmark = pytest.mark.db

FIXTURE = Path(__file__).parent / "fixtures" / "l2" / "branch.json"
SETTINGS = BranchSettings(
    candidate_window_ms=86_400_000,
    max_candidates=5,
    max_incident_tickets=10,
)
ANALYZE_SETTINGS = AnalyzeSettings(
    lookback_ms=259_200_000,
    max_failures=3,
    failure_retry_cooldown_ms=3_600_000,
)
TIME_FIELDS = {
    "fetched_at",
    "time",
    "created_at",
    "updated_at",
    "verified_at",
    "started_at",
}
JSON_FIELDS = {
    "entities",
    "assets",
    "triage",
    "ocsf",
    "verdict",
    "input",
    "output",
    "details",
}


def load_sample() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def insert(conn: psycopg.Connection, table: str, data: dict[str, Any]) -> None:
    values = []
    for name, value in data.items():
        if name in TIME_FIELDS and value is not None:
            value = to_datetime(value)
        elif name in JSON_FIELDS and value is not None:
            value = Jsonb(value)
        values.append(value)
    query = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        sql.Identifier(table),
        sql.SQL(", ").join(map(sql.Identifier, data)),
        sql.SQL(", ").join(sql.Placeholder() * len(data)),
    )
    conn.execute(query, values)
    if table == "tickets":
        enqueue(conn, data["id"])
        conn.execute(
            "UPDATE l2_ticket_index_jobs SET indexed_revision = revision WHERE ticket_id = %s",
            (data["id"],),
        )


@pytest.fixture
def l2_database(temp_database: str) -> tuple[str, dict[str, Any]]:
    migrate(temp_database)
    sample = load_sample()
    groups = [
        ("raw_records", "raw_records"),
        ("alerts", "alerts"),
        ("events", "events"),
        ("hunts", "hunts"),
        ("tickets", "tickets"),
        ("agent_logs", "agent_logs"),
        ("incidents", "incidents"),
    ]
    with psycopg.connect(temp_database) as conn:
        for group, table in groups:
            for data in sample[group]:
                insert(conn, table, data)
    return temp_database, sample


def sample_now(sample: dict[str, Any]) -> datetime:
    return to_datetime(sample["now"])


def test_ticket_index_outbox_versions_are_transactional(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    url, sample = l2_database
    ticket_id = sample["tickets"][0]["id"]
    with psycopg.connect(url) as conn:
        enqueue(conn, ticket_id)
    with psycopg.connect(url) as conn:
        assert conn.execute(
            "SELECT revision, indexed_revision FROM l2_ticket_index_jobs WHERE ticket_id = %s",
            (ticket_id,),
        ).fetchone() == (2, 1)
        with pytest.raises(RuntimeError), conn.transaction():
            enqueue(conn, ticket_id)
            raise RuntimeError("rollback")
        assert conn.execute(
            "SELECT revision FROM l2_ticket_index_jobs WHERE ticket_id = %s", (ticket_id,)
        ).fetchone() == (2,)
        enqueue(conn, ticket_id)
        assert conn.execute(
            "SELECT revision FROM l2_ticket_index_jobs WHERE ticket_id = %s", (ticket_id,)
        ).fetchone() == (3,)


def test_late_ticket_index_write_cannot_replace_new_revision(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    url, sample = l2_database
    ticket_id = sample["tickets"][0]["id"]
    started = threading.Event()
    release = threading.Event()
    writes = []
    failures = []

    class Embedder:
        def embed(self, _text: str) -> list[float]:
            return [1.0, 0.0]

    class Store:
        def upsert(self, _id: str, _vector: list[float], payload: dict[str, Any]) -> None:
            if not writes:
                started.set()
                assert release.wait(5)
            writes.append(payload["revision"])

    service = BranchService(Embedder(), Store())
    with psycopg.connect(url) as conn:
        enqueue(conn, ticket_id)

    def index() -> None:
        try:
            with psycopg.connect(url, autocommit=True) as conn:
                index_one(conn, ticket_id, service)
        except Exception as exc:
            failures.append(type(exc).__name__)

    first = threading.Thread(target=index)
    second = threading.Thread(target=index)
    first.start()
    assert started.wait(5)
    with psycopg.connect(url) as conn:
        enqueue(conn, ticket_id)
    second.start()
    release.set()
    first.join(5)
    second.join(5)
    assert not first.is_alive() and not second.is_alive()
    assert failures == []
    assert writes == [2, 3]


@pytest.mark.qdrant
def test_branch_reindex_detects_missing_point_and_recovers(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    url, sample = l2_database

    class Embedder:
        dimension = 2

        def embed(self, _text: str) -> list[float]:
            return [1.0, 0.0]

    embedder = Embedder()
    store = VectorStore(
        "test_branch_370", embedder, read_store_settings(load_store_config()["store"])
    )
    service = BranchService(embedder, store)
    counts = reindex(url, service, recreate=True)
    assert counts == {
        "processed": len(sample["tickets"]),
        "succeeded": len(sample["tickets"]),
        "failed": 0,
    }
    assert check(url, service) == {"tickets": len(sample["tickets"]), "missing": 0, "stale": 0}
    ticket_id = sample["tickets"][0]["id"]
    with psycopg.connect(url) as conn:
        conn.execute("UPDATE tickets SET status = 'linked' WHERE id = %s", (ticket_id,))
        enqueue(conn, ticket_id)
        assert not index_ready(conn, service)
    with psycopg.connect(url, autocommit=True) as conn:
        assert index_one(conn, ticket_id, service)
        assert index_ready(conn, service)
    payload = store.point_payload(ticket_id.removeprefix("tkt_"))
    assert payload == {"linked": True, "revision": 3}
    store.delete_by_payload("revision", 3)
    with psycopg.connect(url) as conn:
        assert not index_ready(conn, service)
    assert check(url, service)["missing"] >= 1
    assert reindex(url, service, recreate=True)["failed"] == 0
    assert check(url, service)["missing"] == 0


@pytest.mark.qdrant
def test_vector_candidate_uses_current_incident_and_rejects_stale_payload(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    url, sample = l2_database

    class Embedder:
        dimension = 2

        def embed(self, _text: str) -> list[float]:
            return [1.0, 0.0]

    embedder = Embedder()
    store = VectorStore(
        "test_branch_370", embedder, read_store_settings(load_store_config()["store"])
    )
    service = BranchService(embedder, store)
    peer_id = sample["tickets"][0]["id"]
    current_id = sample["tickets"][1]["id"]
    incident_id = sample["incidents"][0]["id"]
    with psycopg.connect(url) as conn:
        conn.execute("UPDATE tickets SET status = 'linked' WHERE id = %s", (peer_id,))
        conn.execute("UPDATE incidents SET ticket_ids = %s WHERE id = %s", ([peer_id], incident_id))
        enqueue(conn, peer_id)
    assert reindex(url, service, recreate=True)["failed"] == 0
    with psycopg.connect(url) as conn:
        text = embedding_text(build_branch(conn, current_id))
        found = find_candidates(
            conn, service, text, current_id, min_score=0.7725, max_incident_tickets=10
        )
        assert (incident_id, peer_id) in [(item.incident["id"], item.ticket_id) for item in found]
        assert all(item.ticket_id == peer_id for item in found)
        enqueue(conn, peer_id)
        assert (
            find_candidates(
                conn, service, text, current_id, min_score=0.7725, max_incident_tickets=10
            )
            == ()
        )


def test_reads_ticket_evidence_without_incidents(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    with psycopg.connect(database_url) as conn:
        rows = read_branch_data(conn, sample["tickets"][0]["id"])

    assert [row["details"]["id"] for row in rows.alerts] == [sample["alerts"][0]["id"]]
    assert [row["details"]["id"] for row in rows.events] == [sample["events"][0]["id"]]
    assert rows.evidence_ids == (
        sample["alerts"][0]["id"],
        sample["events"][0]["id"],
        sample["agent_logs"][0]["id"],
    )
    assert rows.missing_evidence_count == 1


def test_l3_ticket_reads_hunt_evidence_and_builds_context(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    with psycopg.connect(database_url) as conn:
        context = build_branch(conn, sample["tickets"][1]["id"])

    assert context.alerts == ()
    assert context.hunt == sample["hunts"][0]
    assert [event["details"]["id"] for event in context.events] == [sample["events"][1]["id"]]
    assert context.missing_evidence_count == 1


def test_non_escalated_ticket_is_rejected(l2_database: tuple[str, dict[str, Any]]) -> None:
    database_url, sample = l2_database
    with psycopg.connect(database_url) as conn:
        conn.execute(
            "UPDATE tickets SET status = 'linked' WHERE id = %s", (sample["tickets"][0]["id"],)
        )
        with pytest.raises(ValueError, match="escalated"):
            read_branch_data(conn, sample["tickets"][0]["id"])


def ok(output: dict[str, Any]) -> AgentResult:
    return AgentResult(
        ok=True,
        output=output,
        failure=None,
        detail=None,
        run_id="run_01a19f93-1150-7000-8000-000000000201",
    )


def failed(kind: str) -> AgentResult:
    return AgentResult(
        ok=False,
        output=None,
        failure=kind,  # type: ignore[arg-type]
        detail=None,
        run_id="run_01a19f93-1150-7000-8000-000000000202",
    )


def recent_settings(**overrides: Any) -> BranchSettings:
    values = {
        "candidate_window_ms": 86_400_000,
        "max_candidates": 5,
        "max_incident_tickets": 10,
    }
    values.update(overrides)
    return BranchSettings(**values)


def worker(
    database_url: str,
    *,
    run: Any,
    settings: BranchSettings | None = None,
    now: list[int] | None = None,
) -> L2BranchWorker:
    # 이 DB 테스트는 색인 처리 자체가 아니라 분류를 본다. 실색인 테스트는 별도로 둔다.
    with psycopg.connect(database_url) as conn:
        conn.execute(
            "UPDATE l2_ticket_index_jobs SET indexed_revision = revision, failed_revision = NULL"
        )

    class FakeEmbedder:
        def embed(self, _text: str) -> list[float]:
            return [1.0, 0.0]

    class FakeStore:
        def exists(self) -> bool:
            return True

        def count(self) -> int:
            with psycopg.connect(database_url) as conn:
                return conn.execute("SELECT count(*) FROM tickets").fetchone()[0]

        def search(self, _vector, top_k, _filters, *, offset=0, score_threshold=None):
            with psycopg.connect(database_url) as conn:
                rows = conn.execute(
                    """SELECT t.id, j.revision FROM tickets t
                    JOIN l2_ticket_index_jobs j ON j.ticket_id = t.id
                    WHERE t.status = 'linked' ORDER BY t.id LIMIT %s OFFSET %s""",
                    (top_k, offset),
                ).fetchall()
            return tuple(
                SearchHit(row[0].removeprefix("tkt_"), 0.9, {"linked": True, "revision": row[1]})
                for row in rows
            )

    return L2BranchWorker(
        database_url,
        settings or recent_settings(),
        run=run,
        clock=lambda: to_datetime(now[0] if now is not None else 1793764800000),
        service=BranchService(FakeEmbedder(), FakeStore()),
    )


def analyze_worker(database_url: str, run: Any, now: list[int] | None = None) -> L2AnalyzeWorker:
    return L2AnalyzeWorker(
        database_url,
        ANALYZE_SETTINGS,
        max_range_days=7,
        asset_statement_timeout_ms=5000,
        attack_version="20.0",
        run=run,
        clock=lambda: to_datetime(now[0] if now is not None else 1793764800000),
    )


def analysis_outputs(sample: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    alert_id = sample["alerts"][0]["id"]
    event_id = sample["events"][0]["id"]
    log_id = sample["agent_logs"][0]["id"]
    return (
        {
            "timeline": [
                {
                    "time": sample["events"][0]["time"],
                    "summary": "의심 요청 뒤 프로세스가 실행됐다",
                    "evidence_ids": [event_id],
                }
            ],
            "entities": [
                {
                    "entity": {"type": "ip", "value": "203.0.113.55", "role": "src"},
                    "evidence_ids": [alert_id],
                }
            ],
            "evidence_ids": [log_id],
        },
        {
            "verdict": "succeeded",
            "title": "web-01 대상 원격 명령 실행 성공",
            "summary": "침해가 확인됐다",
            "assessed_severity": 5,
            "techniques": [
                {"id": "T1059.001", "evidence_ids": [event_id]},
                {"id": "T9999", "evidence_ids": [alert_id]},
            ],
            "impact": "프로세스 실행",
            "cause": "취약한 요청 처리",
            "further_risk": "재실행 가능성",
            "recommendations": [
                {
                    "kind": "response",
                    "priority": "medium",
                    "title": "서버 점검",
                    "detail": "담당자가 서버를 확인한다",
                    "rationale": "침해가 확인된 호스트다",
                },
                {
                    "kind": "detection",
                    "priority": "high",
                    "title": "프로세스 실행 탐지",
                    "detail": "요청 뒤 프로세스 실행을 탐지한다",
                    "rationale": "요청 직후 웹 서버가 프로세스를 실행했다",
                },
            ],
            "evidence_ids": [],
        },
    )


def prepare_graph_candidate(
    database_url: str,
    sample: dict[str, Any],
    *,
    current_index: int = 1,
    peer_index: int = 0,
    target_index: int = 0,
    duplicate_candidate: bool = False,
) -> str:
    current, peer = sample["tickets"][current_index], sample["tickets"][peer_index]
    target = sample["incidents"][target_index]
    target_id = target["id"]
    peer_entities = (
        sample["hunts"][0]["entities"]
        if current["origin"] == "l3"
        else sample["alerts"][0]["entities"]
    )
    with psycopg.connect(database_url) as conn:
        keep = [target_id]
        duplicate_id = sample["incidents"][1]["id"]
        if duplicate_candidate:
            keep.append(duplicate_id)
        conn.execute("DELETE FROM incidents WHERE id <> ALL(%s)", (keep,))
        conn.execute("UPDATE tickets SET status = 'linked' WHERE id = %s", (peer["id"],))
        conn.execute(
            "UPDATE incidents SET ticket_ids = %s WHERE id = %s", ([peer["id"]], target_id)
        )
        if current["origin"] == "l3":
            conn.execute(
                "UPDATE alerts SET entities = %s WHERE id = %s",
                (Jsonb(peer_entities), sample["alerts"][0]["id"]),
            )
        else:
            conn.execute(
                "UPDATE hunts SET entities = %s WHERE id = %s",
                (Jsonb(peer_entities), sample["hunts"][0]["id"]),
            )
        if duplicate_candidate:
            conn.execute(
                "UPDATE incidents SET ticket_ids = %s, status = 'analyzing', updated_at = %s "
                "WHERE id = %s",
                ([peer["id"]], to_datetime(sample["now"]), duplicate_id),
            )
    return target_id


def fill_incident(
    database_url: str, sample: dict[str, Any], incident_id: str, *, count: int = 10
) -> None:
    peer = sample["tickets"][0]
    ticket_ids = [peer["id"]]
    with psycopg.connect(database_url) as conn:
        for _ in range(count - 1):
            alert = {**sample["alerts"][0], "id": new_id("alt")}
            insert(conn, "alerts", alert)
            clone = {
                **peer,
                "id": new_id("tkt"),
                "status": "linked",
                "alert_ids": [alert["id"]],
            }
            insert(conn, "tickets", clone)
            ticket_ids.append(clone["id"])
        conn.execute(
            "UPDATE incidents SET ticket_ids = %s WHERE id = %s", (ticket_ids, incident_id)
        )


def test_worker_without_graph_path_creates_new_incident_and_saves_coverage(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    with psycopg.connect(database_url) as conn:
        conn.execute("DELETE FROM incidents")

    worker(database_url, run=lambda _: pytest.fail("??? ??? ??? ??? ???")).handle(
        sample["tickets"][0]["id"]
    )

    with psycopg.connect(database_url, row_factory=psycopg.rows.dict_row) as conn:
        ticket = conn.execute(
            "SELECT * FROM tickets WHERE id = %s", (sample["tickets"][0]["id"],)
        ).fetchone()
        incidents = conn.execute("SELECT * FROM incidents").fetchall()
    assert ticket["status"] == "linked"
    branch = ticket["details"]["l2_branch"]
    assert (branch["coverage"], branch["reason"], branch["decision_source"]) == (
        "complete",
        "no_similar_candidate",
        "vector_default",
    )
    assert branch["candidates"] == branch["paths"] == []
    assert len(incidents) == 1
    assert incidents[0]["ticket_ids"] == [sample["tickets"][0]["id"]]


def test_worker_links_incident_using_hunt_to_alert_entity_path(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    target_id = prepare_graph_candidate(database_url, sample)
    peer_id = sample["tickets"][0]["id"]

    def choose(task: Any) -> AgentResult:
        assert task.data["graph"]["coverage"] == "complete"
        assert task.data["candidates"][0]["incident_id"] == target_id
        assert [node["kind"] for node in task.data["candidates"][0]["paths"][0]["nodes"]] == [
            "ticket",
            "hunt",
            "entity",
            "alert",
            "ticket",
            "incident",
        ]
        return ok(
            {
                "decision": "existing",
                "incident_id": target_id,
                "confidence": 0.9,
                "reason": "Hunt? Alert? ??? ??? ????",
                "similar_ticket_ids": [peer_id],
            }
        )

    worker(database_url, run=choose).handle(sample["tickets"][1]["id"])

    with psycopg.connect(database_url, row_factory=psycopg.rows.dict_row) as conn:
        incident = conn.execute("SELECT * FROM incidents WHERE id = %s", (target_id,)).fetchone()
        ticket = conn.execute(
            "SELECT * FROM tickets WHERE id = %s", (sample["tickets"][1]["id"],)
        ).fetchone()
    assert incident["ticket_ids"] == [peer_id, sample["tickets"][1]["id"]]
    assert ticket["details"]["l2_branch"]["coverage"] == "complete"
    assert ticket["details"]["l2_branch"]["reason"] == "paths_found"
    assert ticket["details"]["l2_branch"]["paths"][0]["nodes"][1]["kind"] == "hunt"


def test_src_ip_path_links_existing_incident(l2_database: tuple[str, dict[str, Any]]) -> None:
    database_url, sample = l2_database
    target_id = prepare_graph_candidate(database_url, sample)
    current_id = sample["tickets"][1]["id"]
    ip_entity = {"type": "ip", "value": "192.0.2.7", "role": "src"}
    with psycopg.connect(database_url) as conn:
        conn.execute(
            "UPDATE hunts SET entities = %s WHERE id = %s",
            (Jsonb([ip_entity]), sample["hunts"][0]["id"]),
        )
        conn.execute(
            "UPDATE alerts SET entities = %s WHERE id = %s",
            (Jsonb([ip_entity]), sample["alerts"][0]["id"]),
        )
    worker(
        database_url,
        run=lambda _: ok(
            {
                "decision": "existing",
                "incident_id": target_id,
                "confidence": 0.9,
                "reason": "같은 출발지",
                "similar_ticket_ids": [sample["tickets"][0]["id"]],
            }
        ),
    ).handle(current_id)

    with psycopg.connect(database_url, row_factory=psycopg.rows.dict_row) as conn:
        ticket = conn.execute("SELECT * FROM tickets WHERE id = %s", (current_id,)).fetchone()
        target = conn.execute("SELECT * FROM incidents WHERE id = %s", (target_id,)).fetchone()
    assert ticket["details"]["l2_branch"]["reason"] == "paths_found"
    assert current_id in target["ticket_ids"]


def test_old_open_incident_remains_a_vector_only_candidate(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    target_id = prepare_graph_candidate(database_url, sample)
    current_id = sample["tickets"][1]["id"]
    with psycopg.connect(database_url) as conn:
        conn.execute(
            "UPDATE incidents SET updated_at = %s WHERE id = %s",
            (to_datetime(sample["now"] - 2 * 86_400_000), target_id),
        )

    def choose(task: Any) -> AgentResult:
        candidate = task.data["candidates"][0]
        assert candidate["incident_id"] == target_id
        assert candidate["paths"] == []
        assert candidate["similarity_score"] == 0.9
        return ok(
            {
                "decision": "existing",
                "incident_id": target_id,
                "confidence": 0.9,
                "reason": "동일한 후속 행위",
                "similar_ticket_ids": [candidate["representative_ticket_id"]],
            }
        )

    worker(database_url, run=choose).handle(current_id)
    with psycopg.connect(database_url) as conn:
        ticket_ids = conn.execute(
            "SELECT ticket_ids FROM incidents WHERE id = %s", (target_id,)
        ).fetchone()[0]
    assert current_id in ticket_ids


def test_shared_non_src_host_does_not_link_but_remains_in_incident(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    target_id = prepare_graph_candidate(
        database_url, sample, current_index=0, peer_index=1, target_index=2
    )
    host = {"type": "host", "value": "Shared-Proxy", "role": None}
    with psycopg.connect(database_url) as conn:
        conn.execute(
            "UPDATE hunts SET entities = %s WHERE id = %s",
            (Jsonb([host]), sample["hunts"][0]["id"]),
        )
        conn.execute(
            "UPDATE alerts SET entities = %s WHERE id = %s",
            (Jsonb([host]), sample["alerts"][0]["id"]),
        )

    current_id = sample["tickets"][0]["id"]
    worker(
        database_url,
        run=lambda _: ok(
            {
                "decision": "new",
                "incident_id": None,
                "confidence": 0.8,
                "reason": "행위 문맥이 다름",
                "similar_ticket_ids": [],
            }
        ),
    ).handle(current_id)

    with psycopg.connect(database_url, row_factory=psycopg.rows.dict_row) as conn:
        incident = conn.execute(
            "SELECT * FROM incidents WHERE %s = ANY(ticket_ids)", (current_id,)
        ).fetchone()
        target = conn.execute(
            "SELECT ticket_ids FROM incidents WHERE id = %s", (target_id,)
        ).fetchone()
    assert incident["id"] != target_id
    assert incident["ticket_ids"] == [current_id]
    assert any(entity["type"] == "host" for entity in incident["entities"])
    assert current_id not in target["ticket_ids"]


def test_full_incident_is_excluded_before_candidate_limit(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    full_id = prepare_graph_candidate(database_url, sample, duplicate_candidate=True)
    available_id = sample["incidents"][1]["id"]
    fill_incident(database_url, sample, full_id)
    current_id = sample["tickets"][1]["id"]

    def choose(task: Any) -> AgentResult:
        assert [item["incident_id"] for item in task.data["candidates"]] == [available_id]
        return ok(
            {
                "decision": "existing",
                "incident_id": available_id,
                "confidence": 0.9,
                "reason": "남은 후보",
                "similar_ticket_ids": [sample["tickets"][0]["id"]],
            }
        )

    worker(database_url, run=choose, settings=recent_settings(max_candidates=1)).handle(current_id)

    with psycopg.connect(database_url) as conn:
        full = conn.execute(
            "SELECT ticket_ids FROM incidents WHERE id = %s", (full_id,)
        ).fetchone()[0]
        available = conn.execute(
            "SELECT ticket_ids FROM incidents WHERE id = %s", (available_id,)
        ).fetchone()[0]
    assert len(full) == 10
    assert current_id in available


def test_tenth_ticket_can_join_incident(l2_database: tuple[str, dict[str, Any]]) -> None:
    database_url, sample = l2_database
    target_id = prepare_graph_candidate(database_url, sample)
    fill_incident(database_url, sample, target_id, count=9)
    current_id = sample["tickets"][1]["id"]

    worker(
        database_url,
        run=lambda _: ok(
            {
                "decision": "existing",
                "incident_id": target_id,
                "confidence": 0.9,
                "reason": "열 번째 연결",
                "similar_ticket_ids": [sample["tickets"][0]["id"]],
            }
        ),
    ).handle(current_id)

    with psycopg.connect(database_url) as conn:
        ticket_ids = conn.execute(
            "SELECT ticket_ids FROM incidents WHERE id = %s", (target_id,)
        ).fetchone()[0]
    assert len(ticket_ids) == 10
    assert current_id in ticket_ids


def test_non_src_match_is_excluded_before_candidate_limit(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    valid_id = prepare_graph_candidate(database_url, sample, duplicate_candidate=True)
    invalid_id = sample["incidents"][1]["id"]
    bad_alert = {
        **sample["alerts"][0],
        "id": new_id("alt"),
        "entities": [{"type": "host", "value": "WS-07", "role": None}],
    }
    bad_ticket = {
        **sample["tickets"][0],
        "id": new_id("tkt"),
        "status": "linked",
        "alert_ids": [bad_alert["id"]],
    }
    with psycopg.connect(database_url) as conn:
        insert(conn, "alerts", bad_alert)
        insert(conn, "tickets", bad_ticket)
        conn.execute(
            "UPDATE incidents SET ticket_ids = %s WHERE id = %s",
            ([bad_ticket["id"]], invalid_id),
        )

    current_id = sample["tickets"][1]["id"]

    seen = []

    def choose(task: Any) -> AgentResult:
        seen.extend(item["incident_id"] for item in task.data["candidates"])
        selected = (
            valid_id
            if valid_id in seen
            and any(item["incident_id"] == valid_id for item in task.data["candidates"])
            else None
        )
        return ok(
            {
                "decision": "existing" if selected else "new",
                "incident_id": selected,
                "confidence": 0.9,
                "reason": "벡터 후보의 행위 문맥 비교",
                "similar_ticket_ids": [sample["tickets"][0]["id"]] if selected else [],
            }
        )

    worker(database_url, run=choose, settings=recent_settings(max_candidates=1)).handle(current_id)

    with psycopg.connect(database_url) as conn:
        valid = conn.execute(
            "SELECT ticket_ids FROM incidents WHERE id = %s", (valid_id,)
        ).fetchone()[0]
        invalid = conn.execute(
            "SELECT ticket_ids FROM incidents WHERE id = %s", (invalid_id,)
        ).fetchone()[0]
    assert current_id in valid
    assert current_id not in invalid
    assert set(seen) == {valid_id, invalid_id}


def test_save_rechecks_incident_ticket_limit_after_model_run(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    target_id = prepare_graph_candidate(database_url, sample)
    current_id = sample["tickets"][1]["id"]

    def fill_after_query(_: Any) -> AgentResult:
        fill_incident(database_url, sample, target_id)
        return ok(
            {
                "decision": "existing",
                "incident_id": target_id,
                "confidence": 0.9,
                "reason": "후보 조회 뒤 증가",
                "similar_ticket_ids": [sample["tickets"][0]["id"]],
            }
        )

    worker(database_url, run=fill_after_query).handle(current_id)

    with psycopg.connect(database_url, row_factory=psycopg.rows.dict_row) as conn:
        target = conn.execute(
            "SELECT ticket_ids FROM incidents WHERE id = %s", (target_id,)
        ).fetchone()
        ticket = conn.execute("SELECT details FROM tickets WHERE id = %s", (current_id,)).fetchone()
        created = conn.execute(
            "SELECT ticket_ids FROM incidents WHERE %s = ANY(ticket_ids)", (current_id,)
        ).fetchone()
    assert len(target["ticket_ids"]) == 10
    assert created is None
    assert ticket["details"]["l2_branch"]["reason"] == "candidates_changed"


def test_candidate_limit_reviews_all_batches_before_new_incident(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    prepare_graph_candidate(database_url, sample, duplicate_candidate=True)
    settings = BranchSettings(
        candidate_window_ms=86_400_000, max_candidates=1, max_incident_tickets=10
    )
    current_id = sample["tickets"][1]["id"]

    calls = []

    def choose_new(task: Any) -> AgentResult:
        calls.append(task)
        return ok(
            {
                "decision": "new",
                "incident_id": None,
                "confidence": 0.8,
                "reason": "다른 공격",
                "similar_ticket_ids": [],
            }
        )

    worker(database_url, run=choose_new, settings=settings).handle(current_id)

    with psycopg.connect(database_url, row_factory=psycopg.rows.dict_row) as conn:
        ticket = conn.execute("SELECT * FROM tickets WHERE id = %s", (current_id,)).fetchone()
    branch = ticket["details"]["l2_branch"]
    assert branch["coverage"] == "complete"
    assert branch["decision_source"] == "agent"
    assert len(calls) == 2


def test_agent_failure_keeps_ticket_for_retry(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    prepare_graph_candidate(database_url, sample)
    current_id = sample["tickets"][1]["id"]

    worker(database_url, run=lambda _: failed("provider_error")).handle(current_id)

    with psycopg.connect(database_url, row_factory=psycopg.rows.dict_row) as conn:
        ticket = conn.execute("SELECT * FROM tickets WHERE id = %s", (current_id,)).fetchone()
        incident = conn.execute(
            "SELECT * FROM incidents WHERE %s = ANY(ticket_ids)", (current_id,)
        ).fetchone()
    assert ticket["status"] == "escalated"
    assert ticket["details"]["l2_branch"]["reason"] == "provider_error"
    assert ticket["details"]["l2_branch"]["failures"] == 1
    assert incident is None


def test_three_failures_wait_five_minutes_then_hold_and_operator_resumes_only_l2(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    prepare_graph_candidate(database_url, sample)
    ticket_id = sample["tickets"][1]["id"]
    other_id = new_id("tkt")
    with psycopg.connect(database_url) as conn:
        alert = {**sample["alerts"][0], "id": new_id("alt")}
        insert(conn, "alerts", alert)
        insert(
            conn,
            "tickets",
            {
                **sample["tickets"][0],
                "id": other_id,
                "status": "held",
                "alert_ids": [alert["id"]],
            },
        )
    now = [1793764800000]
    branch = worker(database_url, run=lambda _: failed("format_error"), now=now)
    branch.handle(ticket_id)
    assert ticket_id not in branch.poll(10)
    branch.handle(ticket_id)
    with psycopg.connect(database_url) as conn:
        assert (
            conn.execute(
                "SELECT details->'l2_branch'->>'failures' FROM tickets WHERE id = %s",
                (ticket_id,),
            ).fetchone()[0]
            == "1"
        )
    now[0] += 300_000
    branch.handle(ticket_id)
    now[0] += 300_000
    branch.handle(ticket_id)
    with psycopg.connect(database_url) as conn:
        status, details = conn.execute(
            "SELECT status, details->'l2_branch' FROM tickets WHERE id = %s",
            (ticket_id,),
        ).fetchone()
    assert status == "held" and details["failures"] == 3
    assert details["held_by"] == "l2_branch"
    assert not resume(database_url, other_id)
    assert resume(database_url, ticket_id)
    with psycopg.connect(database_url) as conn:
        assert (
            conn.execute("SELECT status FROM tickets WHERE id = %s", (ticket_id,)).fetchone()[0]
            == "escalated"
        )


def test_cancelled_leaves_ticket_escalated(l2_database: tuple[str, dict[str, Any]]) -> None:
    database_url, sample = l2_database
    prepare_graph_candidate(database_url, sample)
    current_id = sample["tickets"][1]["id"]

    worker(database_url, run=lambda _: failed("cancelled")).handle(current_id)

    with psycopg.connect(database_url) as conn:
        status = conn.execute("SELECT status FROM tickets WHERE id = %s", (current_id,)).fetchone()[
            0
        ]
    assert status == "escalated"


def test_save_rechecks_ticket_state_after_model_run(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    prepare_graph_candidate(database_url, sample)

    def lose_race(task: Any) -> AgentResult:
        with psycopg.connect(database_url, autocommit=True) as conn:
            conn.execute("UPDATE tickets SET status = 'linked' WHERE id = %s", (task.subject_id,))
        return ok(
            {
                "decision": "new",
                "incident_id": None,
                "confidence": 0.8,
                "reason": "? ????",
                "similar_ticket_ids": [],
            }
        )

    worker(database_url, run=lose_race).handle(sample["tickets"][1]["id"])

    with psycopg.connect(database_url) as conn:
        count = conn.execute(
            "SELECT count(*) FROM incidents WHERE %s = ANY(ticket_ids)",
            (sample["tickets"][1]["id"],),
        ).fetchone()[0]
    assert count == 0


def test_save_rechecks_incident_state_after_model_run(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    target_id = prepare_graph_candidate(database_url, sample)

    def close_incident(task: Any) -> AgentResult:
        with psycopg.connect(database_url, autocommit=True) as conn:
            conn.execute("UPDATE incidents SET status = 'confirmed' WHERE id = %s", (target_id,))
        return ok(
            {
                "decision": "existing",
                "incident_id": target_id,
                "confidence": 0.9,
                "reason": "?? ????",
                "similar_ticket_ids": [sample["tickets"][0]["id"]],
            }
        )

    worker(database_url, run=close_incident).handle(sample["tickets"][1]["id"])

    with psycopg.connect(database_url, row_factory=psycopg.rows.dict_row) as conn:
        ticket = conn.execute(
            "SELECT * FROM tickets WHERE id = %s", (sample["tickets"][1]["id"],)
        ).fetchone()
        incident = conn.execute(
            "SELECT * FROM incidents WHERE %s = ANY(ticket_ids)", (sample["tickets"][1]["id"],)
        ).fetchone()
    assert incident is None
    assert ticket["status"] == "escalated"
    assert ticket["details"]["l2_branch"]["reason"] == "candidates_changed"


def test_worker_poll_orders_escalated_ticket_ids(l2_database: tuple[str, dict[str, Any]]) -> None:
    database_url, sample = l2_database
    found = worker(database_url, run=lambda _: failed("cancelled")).poll(1)
    assert found == [min(ticket["id"] for ticket in sample["tickets"])]


def test_existing_incident_severity_uses_max_of_old_and_current_ticket(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    target_id = prepare_graph_candidate(
        database_url, sample, current_index=0, peer_index=1, target_index=2
    )
    current_id, peer_id = sample["tickets"][0]["id"], sample["tickets"][1]["id"]

    worker(
        database_url,
        run=lambda _: ok(
            {
                "decision": "existing",
                "incident_id": target_id,
                "confidence": 0.9,
                "reason": "?? ??? ???",
                "similar_ticket_ids": [peer_id],
            }
        ),
    ).handle(current_id)

    with psycopg.connect(database_url) as conn:
        severity = conn.execute(
            "SELECT severity FROM incidents WHERE id = %s", (target_id,)
        ).fetchone()[0]
    assert severity == sample["alerts"][0]["severity"]


def prepare_analyzing_incident(
    database_url: str, sample: dict[str, Any], *, analysis_round: int = 0
) -> str:
    incident_id = sample["incidents"][0]["id"]
    ticket_id = sample["tickets"][0]["id"]
    with psycopg.connect(database_url) as conn:
        conn.execute("DELETE FROM incidents WHERE id <> %s", (incident_id,))
        conn.execute("UPDATE tickets SET status = 'linked' WHERE id = %s", (ticket_id,))
        conn.execute(
            "UPDATE incidents SET status = 'analyzing', analysis_round = %s, details = '{}' "
            "WHERE id = %s",
            (analysis_round, incident_id),
        )
        conn.execute(
            "INSERT INTO attack_techniques (attack_version, technique_id, name, tactics) "
            "VALUES ('20.0', 'T1059.001', 'PowerShell', ARRAY['execution'])"
        )
    return incident_id


def test_analyze_context_uses_saved_graph_and_does_not_collect_related_records(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    incident_id = prepare_analyzing_incident(database_url, sample)
    ticket_id = sample["tickets"][0]["id"]
    graph = {
        "coverage": "incomplete",
        "reason": "candidate_limit",
        "paths": [
            {
                "incident_id": incident_id,
                "ticket_id": sample["tickets"][1]["id"],
                "nodes": [
                    {"id": ticket_id, "kind": "ticket"},
                    {"id": sample["alerts"][0]["id"], "kind": "alert"},
                    {
                        "id": "host:shared-proxy",
                        "kind": "entity",
                        "type": "host",
                        "value": "shared-proxy",
                    },
                    {"id": "alt_peer", "kind": "alert"},
                    {"id": sample["tickets"][1]["id"], "kind": "ticket"},
                    {"id": incident_id, "kind": "incident"},
                ],
                "edges": [],
            }
        ],
    }
    with psycopg.connect(database_url) as conn:
        conn.execute(
            "UPDATE tickets SET details = jsonb_set(details, '{l2_branch}', %s) WHERE id = %s",
            (Jsonb(graph), ticket_id),
        )
        context = analyze_context.read_context(
            conn,
            incident_id,
            ANALYZE_SETTINGS,
            now_ms=sample["now"],
            max_range_days=7,
            asset_statement_timeout_ms=5000,
        )

    assert context is not None
    assert context.investigate_data()["graph"]["tickets"] == [{"ticket_id": ticket_id, **graph}]
    assert "related" not in context.investigate_data()
    assert sample["events"][1]["id"] not in context.evidence_ids
    task = make_investigate_task(
        incident_id,
        attempt=1,
        data=context.investigate_data(),
        allowed_evidence_ids=context.evidence_ids,
    )
    chars = input_chars(
        compose_instructions(task, max_turns=12),
        [{"role": "user", "content": wrap_data(task.data)}],
    )
    assert chars <= 64_000


def test_analyze_worker_saves_artifact_proposals_and_incident_atomically(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    incident_id = prepare_analyzing_incident(database_url, sample)
    findings, analysis = analysis_outputs(sample)
    tasks = []

    def run(task):
        tasks.append(task)
        return ok(findings if task.task == "l2_investigate" else analysis)

    analyzer = analyze_worker(database_url, run)
    analyzer.handle(incident_id)
    analyzer.handle(incident_id)

    with psycopg.connect(database_url, row_factory=psycopg.rows.dict_row) as conn:
        incident = conn.execute("SELECT * FROM incidents WHERE id = %s", (incident_id,)).fetchone()
        artifact = conn.execute(
            "SELECT * FROM incident_artifacts WHERE incident_id = %s", (incident_id,)
        ).fetchone()
        proposals = conn.execute("SELECT * FROM incident_proposals ORDER BY seq").fetchall()
    assert [task.task for task in tasks] == ["l2_investigate", "l2_report"]
    assert set(tasks[0].allowed_evidence_ids) >= {
        sample["alerts"][0]["id"],
        sample["events"][0]["id"],
        sample["agent_logs"][0]["id"],
    }
    assert incident["status"] == "awaiting_review"
    assert incident["analysis_round"] == 1
    assert incident["summary"] == analysis["summary"]
    assert incident["details"]["l2_analyze"] == {
        "asset_lookup_failed": False,
        "dropped_techniques": 1,
        # 조사가 고른 SIEM 문서 중 저장하지 못해 버린 수(#382). 이 사례는 0건이다
        "dropped_refs": 0,
        "failure_streak": 0,
    }
    assert {item["value"] for item in incident["entities"]} >= {"203.0.113.55"}
    assert artifact["verdict"] == "succeeded"
    assert artifact["techniques"] == [
        {"id": "T1059.001", "name": "PowerShell", "evidence_ids": [sample["events"][0]["id"]]}
    ]
    assert set(artifact["evidence_ids"]) == {
        sample["alerts"][0]["id"],
        sample["events"][0]["id"],
        sample["agent_logs"][0]["id"],
    }
    # 대응·탐지가 한 목록에 섞여 모델이 낸 순서(seq 1..n)대로 저장된다. 룰 내용은 detail에 남는다
    assert [
        (row["kind"], row["seq"], row["priority"], row["title"], row["detail"], row["rationale"])
        for row in proposals
    ] == [
        (item["kind"], seq, item["priority"], item["title"], item["detail"], item["rationale"])
        for seq, item in enumerate(analysis["recommendations"], 1)
    ]
    assert incident["title"] == analysis["title"]


def test_analyze_worker_retries_only_report_without_repeating_investigation(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    incident_id = prepare_analyzing_incident(database_url, sample)
    findings, analysis = analysis_outputs(sample)
    results = iter([ok(findings), failed("provider_error"), ok(analysis)])
    tasks = []

    def run(task):
        tasks.append(task)
        return next(results)

    analyze_worker(database_url, run).handle(incident_id)

    assert [task.task for task in tasks] == ["l2_investigate", "l2_report", "l2_report"]
    assert tasks[1] is tasks[2]
    with psycopg.connect(database_url) as conn:
        assert conn.execute(
            "SELECT analysis_round, status FROM incidents WHERE id = %s", (incident_id,)
        ).fetchone() == (1, "awaiting_review")


@pytest.mark.parametrize(
    ("result", "expected_round"),
    [(failed("format_error"), 1), (failed("cancelled"), 0)],
    ids=["failed", "cancelled"],
)
def test_analyze_worker_failure_round_and_cancelled(
    l2_database: tuple[str, dict[str, Any]], result: AgentResult, expected_round: int
) -> None:
    database_url, sample = l2_database
    incident_id = prepare_analyzing_incident(database_url, sample)
    calls = 0

    def run(_):
        nonlocal calls
        calls += 1
        return result

    analyze_worker(database_url, run).handle(incident_id)

    with psycopg.connect(database_url, row_factory=psycopg.rows.dict_row) as conn:
        incident = conn.execute("SELECT * FROM incidents WHERE id = %s", (incident_id,)).fetchone()
        artifact_count = conn.execute(
            "SELECT count(*) AS count FROM incident_artifacts"
        ).fetchone()["count"]
    assert calls == 1
    assert incident["analysis_round"] == expected_round
    assert incident["status"] == "analyzing"
    assert incident["details"].get("l2_analyze", {}).get("failure_streak", 0) == expected_round
    assert artifact_count == 0


def test_three_failures_hold_until_cooldown_even_if_ticket_updates_incident(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    incident_id = prepare_analyzing_incident(database_url, sample)
    findings, analysis = analysis_outputs(sample)
    now = [1793764800000]
    calls = 0

    def run(task):
        nonlocal calls
        calls += 1
        if calls <= 3:
            now[0] += 60_000  # held_at은 모델을 부르기 전이 아니라 실패 저장 시각이다.
            return failed("format_error")
        return ok(findings if task.task == "l2_investigate" else analysis)

    analyzer = analyze_worker(database_url, run, now)
    for _ in range(3):
        analyzer.handle(incident_id)
    with psycopg.connect(database_url) as conn:
        status, round_number, details = conn.execute(
            "SELECT status, analysis_round, details FROM incidents WHERE id = %s", (incident_id,)
        ).fetchone()
        conn.execute(
            "UPDATE incidents SET updated_at = %s WHERE id = %s",
            (to_datetime(now[0] + 900_000), incident_id),
        )
    assert (status, round_number) == ("held", 3)
    assert details["l2_analyze"]["failure_streak"] == 3
    assert details["l2_analyze"]["held_at"] == now[0]
    now[0] += 3_600_000 - 1
    assert incident_id not in analyzer.poll(10)
    analyzer.handle(incident_id)
    assert calls == 3
    now[0] += 1
    assert incident_id in analyzer.poll(10)
    analyzer.handle(incident_id)
    with psycopg.connect(database_url) as conn:
        status, round_number, details = conn.execute(
            "SELECT status, analysis_round, details FROM incidents WHERE id = %s", (incident_id,)
        ).fetchone()
        artifacts = conn.execute(
            "SELECT count(*) FROM incident_artifacts WHERE incident_id = %s", (incident_id,)
        ).fetchone()[0]
    assert (status, round_number, artifacts) == ("awaiting_review", 4, 1)
    assert details["l2_analyze"]["failure_streak"] == 0
    assert len(details["l2_analyze"]["failures"]) == 3


def test_analyze_worker_has_no_round_limit(l2_database: tuple[str, dict[str, Any]]) -> None:
    database_url, sample = l2_database
    incident_id = prepare_analyzing_incident(database_url, sample, analysis_round=5)
    findings, analysis = analysis_outputs(sample)
    analyzer = analyze_worker(
        database_url,
        lambda task: ok(findings if task.task == "l2_investigate" else analysis),
    )

    analyzer.handle(incident_id)

    with psycopg.connect(database_url) as conn:
        assert conn.execute(
            "SELECT status, analysis_round FROM incidents WHERE id = %s", (incident_id,)
        ).fetchone() == ("awaiting_review", 6)


def test_six_new_tickets_each_trigger_analysis(l2_database: tuple[str, dict[str, Any]]) -> None:
    database_url, sample = l2_database
    incident_id = prepare_analyzing_incident(database_url, sample)
    findings, analysis = analysis_outputs(sample)
    analyzer = analyze_worker(
        database_url,
        lambda task: ok(findings if task.task == "l2_investigate" else analysis),
    )
    analyzer.handle(incident_id)

    for number in range(1, 7):
        suffix = f"01a19f93-1150-7000-8000-{200 + number:012d}"
        raw_id, alert_id, ticket_id = (f"{prefix}_{suffix}" for prefix in ("raw", "alt", "tkt"))
        with psycopg.connect(database_url) as conn:
            insert(
                conn,
                "raw_records",
                {**sample["raw_records"][0], "id": raw_id, "siem_ref": f"test-270-{number}"},
            )
            insert(
                conn,
                "alerts",
                {**sample["alerts"][0], "id": alert_id, "raw_id": raw_id},
            )
            ticket = sample["tickets"][0]
            insert(
                conn,
                "tickets",
                {
                    **ticket,
                    "id": ticket_id,
                    "alert_ids": [alert_id],
                    "verdict": {**ticket["verdict"], "evidence_ids": [alert_id]},
                },
            )
        worker(
            database_url,
            run=lambda _: ok(
                {
                    "decision": "existing",
                    "incident_id": incident_id,
                    "confidence": 0.9,
                    "reason": "같은 공격이다",
                    "similar_ticket_ids": [],
                }
            ),
        ).handle(ticket_id)
        analyzer.handle(incident_id)
        with psycopg.connect(database_url) as conn:
            assert conn.execute(
                "SELECT status, analysis_round FROM incidents WHERE id = %s", (incident_id,)
            ).fetchone() == ("awaiting_review", number + 1)

    with psycopg.connect(database_url) as conn:
        assert conn.execute(
            "SELECT count(*) FROM incident_artifacts WHERE incident_id = %s", (incident_id,)
        ).fetchone() == (7,)


def test_migration_revives_old_round_limit_incident(temp_database: str, tmp_path: Path) -> None:
    for name in ("0001_common_tables.sql", "0200_incident_artifacts.sql"):
        (tmp_path / name).write_bytes((MIGRATIONS_DIR / name).read_bytes())
    migrate(temp_database, tmp_path)
    incident = load_sample()["incidents"][0]
    incident["analysis_round"] = 5
    incident["details"] = {"l2_analyze": {"stopped": "round_limit", "failures": []}}
    with psycopg.connect(temp_database) as conn:
        insert(conn, "incidents", incident)

    migrate(temp_database)

    with psycopg.connect(temp_database) as conn:
        status, round_number, details = conn.execute(
            "SELECT status, analysis_round, details FROM incidents WHERE id = %s", (incident["id"],)
        ).fetchone()
    assert (status, round_number) == ("analyzing", 5)
    assert details["l2_analyze"] == {"failures": []}


def test_reanalysis_receives_previous_artifact(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    incident_id = prepare_analyzing_incident(database_url, sample)
    findings, analysis = analysis_outputs(sample)
    tasks = []

    def run(task):
        tasks.append(task)
        return ok(findings if task.task == "l2_investigate" else analysis)

    analyzer = analyze_worker(database_url, run)
    analyzer.handle(incident_id)
    with psycopg.connect(database_url) as conn:
        conn.execute("UPDATE incidents SET status = 'analyzing' WHERE id = %s", (incident_id,))
    analyzer.handle(incident_id)

    previous = tasks[2].data["previous_artifact"]
    assert previous["analysis_round"] == 1
    assert tasks[3].data["previous_artifact"] == previous
    assert set(previous["evidence_ids"]) <= set(tasks[2].allowed_evidence_ids)
    with psycopg.connect(database_url) as conn:
        assert conn.execute(
            "SELECT analysis_round FROM incidents WHERE id = %s", (incident_id,)
        ).fetchone() == (2,)
        assert conn.execute(
            "SELECT count(*) FROM incident_artifacts WHERE incident_id = %s", (incident_id,)
        ).fetchone() == (2,)


def test_ticket_added_during_analysis_keeps_next_analysis_pending(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    incident_id = prepare_analyzing_incident(database_url, sample)
    extra_ticket_id = sample["tickets"][1]["id"]
    findings, analysis = analysis_outputs(sample)
    tasks = []

    def run(task):
        tasks.append(task)
        if task.task == "l2_report" and len(tasks) == 2:
            with psycopg.connect(database_url) as conn:
                conn.execute(
                    "UPDATE tickets SET status = 'linked' WHERE id = %s", (extra_ticket_id,)
                )
                conn.execute(
                    "UPDATE incidents SET ticket_ids = array_append(ticket_ids, %s) WHERE id = %s",
                    (extra_ticket_id, incident_id),
                )
        return ok(findings if task.task == "l2_investigate" else analysis)

    analyzer = analyze_worker(database_url, run)
    analyzer.handle(incident_id)
    with psycopg.connect(database_url) as conn:
        assert conn.execute(
            "SELECT status, analysis_round, ticket_ids FROM incidents WHERE id = %s", (incident_id,)
        ).fetchone() == ("analyzing", 1, [sample["tickets"][0]["id"], extra_ticket_id])
        assert conn.execute(
            "SELECT count(*) FROM incident_artifacts WHERE incident_id = %s", (incident_id,)
        ).fetchone() == (1,)

    analyzer.handle(incident_id)

    assert {ticket["id"] for ticket in tasks[2].data["tickets"]} == {
        sample["tickets"][0]["id"],
        extra_ticket_id,
    }
    with psycopg.connect(database_url) as conn:
        assert conn.execute(
            "SELECT status, analysis_round FROM incidents WHERE id = %s", (incident_id,)
        ).fetchone() == ("awaiting_review", 2)
        assert conn.execute(
            "SELECT count(*) FROM incident_artifacts WHERE incident_id = %s", (incident_id,)
        ).fetchone() == (2,)


def test_asset_lookup_failure_is_shown_to_both_runs_and_incident(
    l2_database: tuple[str, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    database_url, sample = l2_database
    incident_id = prepare_analyzing_incident(database_url, sample)
    findings, analysis = analysis_outputs(sample)
    tasks = []

    def fail_lookup(*_args, **_kwargs):
        raise AssetLookupError

    monkeypatch.setattr(analyze_context, "lookup_assets", fail_lookup)

    def run(task):
        tasks.append(task)
        return ok(findings if task.task == "l2_investigate" else analysis)

    analyze_worker(database_url, run).handle(incident_id)

    assert [task.data["asset_lookup_failed"] for task in tasks] == [True, True]
    with psycopg.connect(database_url) as conn:
        details = conn.execute(
            "SELECT details FROM incidents WHERE id = %s", (incident_id,)
        ).fetchone()[0]
    assert details["l2_analyze"]["asset_lookup_failed"] is True


def test_store_rechecks_round_after_model_calls(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    incident_id = prepare_analyzing_incident(database_url, sample)
    findings, analysis = analysis_outputs(sample)

    def run(task):
        if task.task == "l2_report":
            with psycopg.connect(database_url) as conn:
                conn.execute(
                    "UPDATE incidents SET analysis_round = 3 WHERE id = %s", (incident_id,)
                )
            return ok(analysis)
        return ok(findings)

    analyze_worker(database_url, run).handle(incident_id)

    with psycopg.connect(database_url) as conn:
        assert conn.execute(
            "SELECT analysis_round, status FROM incidents WHERE id = %s", (incident_id,)
        ).fetchone() == (3, "analyzing")
        assert conn.execute("SELECT count(*) FROM incident_artifacts").fetchone() == (0,)


@pytest.mark.parametrize(
    ("verdict", "expected_status"),
    [("not_threat", "dismissed"), ("inconclusive", "awaiting_review")],
)
def test_analysis_verdict_sets_terminal_status(
    l2_database: tuple[str, dict[str, Any]], verdict: str, expected_status: str
) -> None:
    database_url, sample = l2_database
    incident_id = prepare_analyzing_incident(database_url, sample)
    findings, analysis = analysis_outputs(sample)
    analysis = {**analysis, "verdict": verdict}
    if verdict == "inconclusive":
        findings = {"timeline": [], "entities": [], "evidence_ids": []}
        analysis = {**analysis, "techniques": [], "evidence_ids": []}
    results = iter((ok(findings), ok(analysis)))

    analyze_worker(database_url, lambda _: next(results)).handle(incident_id)

    with psycopg.connect(database_url) as conn:
        assert conn.execute(
            "SELECT status FROM incidents WHERE id = %s", (incident_id,)
        ).fetchone() == (expected_status,)


def run_analysis(
    database_url: str, sample: dict[str, Any], incident_id: str, **analysis_changes: Any
) -> dict[str, Any]:
    """가짜 모델로 한 번 분석한다. 모델이 낸 보고 출력을 돌려준다."""
    findings, analysis = analysis_outputs(sample)
    analysis = {**analysis, **analysis_changes}
    validate_contract("incident_analysis", analysis)  # 가짜 모델도 계약이 허용하는 출력만 낸다
    analyze_worker(
        database_url, lambda task: ok(findings if task.task == "l2_investigate" else analysis)
    ).handle(incident_id)
    return analysis


def incident_row(database_url: str, incident_id: str) -> dict[str, Any]:
    with psycopg.connect(database_url, row_factory=psycopg.rows.dict_row) as conn:
        row = conn.execute("SELECT * FROM incidents WHERE id = %s", (incident_id,)).fetchone()
    assert row is not None
    return row


def test_analysis_overwrites_the_provisional_title_with_the_cleaned_ai_title(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    incident_id = prepare_analyzing_incident(database_url, sample)
    provisional = sample["incidents"][0]["title"]
    assert incident_row(database_url, incident_id)["title"] == provisional

    run_analysis(database_url, sample, incident_id, title="  web-01 대상 \n SQL\u3000인젝션 시도 ")

    assert incident_row(database_url, incident_id)["title"] == "web-01 대상 SQL 인젝션 시도"


def test_analysis_clips_a_long_ai_title_like_a_ticket_title(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    incident_id = prepare_analyzing_incident(database_url, sample)

    run_analysis(database_url, sample, incident_id, title="가" * 300)

    assert incident_row(database_url, incident_id)["title"] == "가" * 199 + "…"


@pytest.mark.parametrize("title", ["", "   ", "\t\n\u00a0\u3000", FALLBACK_TITLE])
def test_unusable_ai_title_keeps_the_provisional_title_and_saves_the_round_once(
    l2_database: tuple[str, dict[str, Any]], title: str
) -> None:
    """빈 제목은 계약 오류가 아니다. 라운드가 한 번에 저장되고 다시 분석하지 않는다(D-059)."""
    database_url, sample = l2_database
    incident_id = prepare_analyzing_incident(database_url, sample)
    run_calls: list[str] = []
    findings, analysis = analysis_outputs(sample)
    analysis = {**analysis, "title": title}
    validate_contract("incident_analysis", analysis)

    def run(task: Any) -> AgentResult:
        run_calls.append(task.task)
        return ok(findings if task.task == "l2_investigate" else analysis)

    analyzer = analyze_worker(database_url, run)
    analyzer.handle(incident_id)
    analyzer.handle(incident_id)  # 이미 awaiting_review라 아무 일도 하지 않는다

    row = incident_row(database_url, incident_id)
    assert row["title"] == sample["incidents"][0]["title"]
    assert row["status"] == "awaiting_review"
    assert row["analysis_round"] == 1
    assert row["details"]["l2_analyze"]["failure_streak"] == 0
    assert run_calls == ["l2_investigate", "l2_report"]
    with psycopg.connect(database_url) as conn:
        assert conn.execute("SELECT count(*) FROM incident_artifacts").fetchone() == (1,)


def test_failed_analysis_keeps_the_provisional_title(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    incident_id = prepare_analyzing_incident(database_url, sample)

    analyze_worker(database_url, lambda _: failed("provider_error")).handle(incident_id)

    assert incident_row(database_url, incident_id)["title"] == sample["incidents"][0]["title"]


def test_reanalysis_updates_the_title_again(l2_database: tuple[str, dict[str, Any]]) -> None:
    database_url, sample = l2_database
    incident_id = prepare_analyzing_incident(database_url, sample)

    run_analysis(database_url, sample, incident_id, title="첫 분석 제목")
    with psycopg.connect(database_url) as conn:
        conn.execute("UPDATE incidents SET status = 'analyzing' WHERE id = %s", (incident_id,))
    run_analysis(database_url, sample, incident_id, title="재분석 제목")

    assert incident_row(database_url, incident_id)["title"] == "재분석 제목"


def test_reanalysis_with_an_unusable_title_keeps_the_previous_ai_title(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    incident_id = prepare_analyzing_incident(database_url, sample)

    run_analysis(database_url, sample, incident_id, title="첫 분석 제목")
    with psycopg.connect(database_url) as conn:
        conn.execute("UPDATE incidents SET status = 'analyzing' WHERE id = %s", (incident_id,))
    run_analysis(database_url, sample, incident_id, title="   ")

    assert incident_row(database_url, incident_id)["title"] == "첫 분석 제목"


def test_not_threat_analysis_also_updates_the_title(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    incident_id = prepare_analyzing_incident(database_url, sample)

    run_analysis(
        database_url,
        sample,
        incident_id,
        verdict="not_threat",
        title="정상 점검 요청",
        recommendations=[],
    )

    row = incident_row(database_url, incident_id)
    assert (row["status"], row["title"]) == ("dismissed", "정상 점검 요청")


def test_recommendation_titles_are_cleaned_and_stored_in_list_order(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    incident_id = prepare_analyzing_incident(database_url, sample)
    _, analysis = analysis_outputs(sample)
    recommendations = [
        {**analysis["recommendations"][0], "title": " 서버 \n  점검\u3000필요 "},
        analysis["recommendations"][1],
    ]

    run_analysis(database_url, sample, incident_id, recommendations=recommendations)

    with psycopg.connect(database_url) as conn:
        rows = conn.execute("SELECT seq, title FROM incident_proposals ORDER BY seq").fetchall()
    assert rows == [(1, "서버 점검 필요"), (2, analysis["recommendations"][1]["title"])]


def test_branch_candidate_shows_the_ai_title_after_analysis(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    """분석이 끝나면 브랜치 판단 LLM이 보는 후보 Incident 제목이 AI 제목으로 바뀐다(D-072)."""
    database_url, sample = l2_database
    target_id = prepare_graph_candidate(database_url, sample)
    peer_id = sample["tickets"][0]["id"]
    with psycopg.connect(database_url) as conn:
        conn.execute(
            "INSERT INTO attack_techniques (attack_version, technique_id, name, tactics) "
            "VALUES ('20.0', 'T1059.001', 'PowerShell', ARRAY['execution'])"
        )
    seen: list[dict[str, Any]] = []

    def choose(task: Any) -> AgentResult:
        seen.extend(task.data["candidates"])
        return ok(
            {
                "decision": "existing",
                "incident_id": target_id,
                "confidence": 0.9,
                "reason": "같은 출발지",
                "similar_ticket_ids": [peer_id],
            }
        )

    run_analysis(database_url, sample, target_id)
    worker(database_url, run=choose).handle(sample["tickets"][1]["id"])

    assert [item["incident_id"] for item in seen] == [target_id]
    assert seen[0]["title"] == "web-01 대상 원격 명령 실행 성공"
    assert seen[0]["title"] != sample["incidents"][0]["title"]
    assert seen[0]["ticket_count"] == 1
