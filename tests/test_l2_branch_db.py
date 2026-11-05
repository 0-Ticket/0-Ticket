"""L2 분류 입력을 PostgreSQL에서 읽는 경계를 확인한다(db 마커)."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

from soc.agent import AgentResult
from soc.asset_lookup import AssetLookupError
from soc.contracts import to_datetime
from soc.db.migrate import migrate
from soc.l2.analyze import context as analyze_context
from soc.l2.analyze.worker import L2AnalyzeWorker
from soc.l2.branch import build_branch
from soc.l2.branch.read import (
    _RECENT_INCIDENTS_QUERY,
    read_branch_data,
    read_hit_tickets,
    read_incidents_by_ids,
    read_recent_incidents,
)
from soc.l2.branch.worker import L2BranchWorker
from soc.l2.config import AnalyzeSettings, BranchSettings
from soc.l2.reindex import reindex
from soc.store import CollectionMissing, SearchHit, StoreError

pytestmark = pytest.mark.db

FIXTURE = Path(__file__).parent / "fixtures" / "l2" / "branch.json"
SETTINGS = BranchSettings(
    candidate_window_ms=86_400_000,
    max_candidates=5,
    candidate_source="vector",
    top_k=50,
)
ANALYZE_SETTINGS = AnalyzeSettings(
    lookback_ms=86_400_000,
    max_analysis_rounds=5,
    max_seed_entities=10,
    max_related_per_entity=20,
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
    "original",
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


def test_reads_ticket_evidence_without_incidents(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    with psycopg.connect(database_url) as conn:
        rows = read_branch_data(conn, sample["tickets"][0]["id"])

    assert [row["id"] for row in rows.alerts] == [sample["alerts"][0]["id"]]
    assert [row["id"] for row in rows.events] == [sample["events"][0]["id"]]
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
    assert [event["id"] for event in context.events] == [sample["events"][1]["id"]]
    assert context.missing_evidence_count == 1


def test_non_escalated_ticket_is_rejected(l2_database: tuple[str, dict[str, Any]]) -> None:
    database_url, sample = l2_database
    with psycopg.connect(database_url) as conn:
        conn.execute(
            "UPDATE tickets SET status = 'linked' WHERE id = %s", (sample["tickets"][0]["id"],)
        )
        with pytest.raises(ValueError, match="escalated"):
            read_branch_data(conn, sample["tickets"][0]["id"])


def test_recent_incidents_are_open_in_window_and_limited(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    with psycopg.connect(database_url) as conn:
        incidents = read_recent_incidents(
            conn,
            sample_now(sample),
            SETTINGS.candidate_window_ms,
            limit=2,
        )

    assert [row["id"] for row in incidents] == [
        sample["incidents"][1]["id"],
        sample["incidents"][2]["id"],
    ]


def test_vector_incident_lookup_separates_open_and_closed(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    ids = [sample["incidents"][0]["id"], sample["incidents"][3]["id"]]
    with psycopg.connect(database_url) as conn:
        lookup = read_incidents_by_ids(conn, ids, sample_now(sample), SETTINGS.candidate_window_ms)

    assert set(lookup.open) == {sample["incidents"][0]["id"]}
    assert lookup.closed_ids == (sample["incidents"][3]["id"],)


def test_hit_tickets_include_representative_alert_or_hunt_title(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    ids = [sample["tickets"][0]["id"], sample["tickets"][1]["id"]]
    with psycopg.connect(database_url) as conn:
        tickets = read_hit_tickets(conn, ids)

    assert tickets[ids[0]]["title"] == sample["alerts"][0]["title"]
    assert tickets[ids[1]]["title"] == sample["hunts"][0]["hypothesis"]


def test_recent_incident_query_uses_status_index(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    now = sample_now(sample)
    cutoff = to_datetime(sample["now"] - SETTINGS.candidate_window_ms)
    with psycopg.connect(database_url) as conn:
        conn.execute("SET enable_seqscan = off")
        rows = conn.execute(
            "EXPLAIN " + _RECENT_INCIDENTS_QUERY,
            (["analyzing", "awaiting_review", "human_handling"], cutoff, now, 5),
        ).fetchall()

    plan = "\n".join(row[0] for row in rows)
    assert "incidents_status_idx" in plan, plan


class FakeEmbedder:
    dimension = 2

    def embed(self, text: str) -> list[float]:
        assert text
        return [1.0, 0.0]


class FakeStore:
    def __init__(self) -> None:
        self.upserts: list[tuple[str, list[float], dict[str, str]]] = []
        self.ensured = 0
        self.dropped = 0

    def exists(self) -> bool:
        return True

    def ensure_collection(self) -> None:
        self.ensured += 1

    def drop_collection(self) -> None:
        self.dropped += 1

    def upsert(self, point_id: str, vector: list[float], payload: dict[str, str]) -> None:
        self.upserts.append((point_id, vector, payload))


class FakeSearchStore(FakeStore):
    def __init__(
        self,
        hits: tuple[SearchHit, ...] = (),
        error: StoreError | None = None,
    ) -> None:
        super().__init__()
        self.hits = hits
        self.error = error
        self.deleted: list[tuple[str, str]] = []

    def search(self, vector: list[float], top_k: int) -> tuple[SearchHit, ...]:
        assert vector == [1.0, 0.0]
        assert top_k == 50
        if self.error is not None:
            raise self.error
        return self.hits

    def delete_by_payload(self, key: str, value: str) -> None:
        self.deleted.append((key, value))


class FailingUpsertStore(FakeStore):
    def upsert(self, point_id: str, vector: list[float], payload: dict[str, str]) -> None:
        raise CollectionMissing()


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
        "candidate_source": "recent",
        "top_k": 50,
    }
    values.update(overrides)
    return BranchSettings(**values)


def worker(
    database_url: str,
    *,
    run: Any,
    store: FakeStore | None = None,
    settings: BranchSettings | None = None,
) -> L2BranchWorker:
    return L2BranchWorker(
        database_url,
        settings or recent_settings(),
        FakeEmbedder(),
        store or FakeStore(),
        run=run,
        clock=lambda: to_datetime(1793764800000),
    )


def analyze_worker(database_url: str, run: Any) -> L2AnalyzeWorker:
    return L2AnalyzeWorker(
        database_url,
        ANALYZE_SETTINGS,
        max_range_days=7,
        asset_statement_timeout_ms=5000,
        attack_version="20.0",
        run=run,
        clock=lambda: to_datetime(1793764800000),
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
            "summary": "침해가 확인됐다",
            "assessed_severity": 5,
            "techniques": [
                {"id": "T1059.001", "evidence_ids": [event_id]},
                {"id": "T9999", "evidence_ids": [alert_id]},
            ],
            "impact": "프로세스 실행",
            "cause": "취약한 요청 처리",
            "further_risk": "재실행 가능성",
            "detection_rules": ["요청 뒤 프로세스 실행을 탐지한다"],
            "response_actions": ["담당자가 서버를 확인한다"],
            "evidence_ids": [],
        },
    )


def test_worker_creates_new_incident_and_indexes_ticket(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    vector_store = FakeStore()
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("DELETE FROM incidents")

    branch_worker = worker(
        database_url,
        run=lambda _: pytest.fail("후보가 없으면 모델을 부르지 않는다"),
        store=vector_store,
    )
    branch_worker.handle(sample["tickets"][0]["id"])

    with psycopg.connect(database_url, row_factory=psycopg.rows.dict_row) as conn:
        ticket = conn.execute(
            "SELECT * FROM tickets WHERE id = %s", (sample["tickets"][0]["id"],)
        ).fetchone()
        incidents = conn.execute("SELECT * FROM incidents").fetchall()
    assert ticket["status"] == "linked"
    assert ticket["details"]["l2_branch"] == {
        "candidate_source": "recent",
        "candidate_fallback": None,
        "invalid_hit_count": 0,
        "decision_source": "no_candidates",
        "decision_fallback": None,
    }
    assert len(incidents) == 1
    assert incidents[0]["status"] == "analyzing"
    assert incidents[0]["severity"] == 4
    assert incidents[0]["ticket_ids"] == [sample["tickets"][0]["id"]]
    assert vector_store.upserts[0][2] == {"incident_id": incidents[0]["id"]}


def test_worker_links_existing_and_reopens_awaiting_review(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    target = sample["incidents"][1]

    def choose(task: Any) -> AgentResult:
        assert task.data["candidates"][0]["incident_id"] == target["id"]
        return ok(
            {
                "decision": "existing",
                "incident_id": target["id"],
                "confidence": 0.9,
                "reason": "같은 공격이다",
                "similar_ticket_ids": [],
            }
        )

    worker(database_url, run=choose).handle(sample["tickets"][1]["id"])

    with psycopg.connect(database_url, row_factory=psycopg.rows.dict_row) as conn:
        incident = conn.execute("SELECT * FROM incidents WHERE id = %s", (target["id"],)).fetchone()
        ticket = conn.execute(
            "SELECT * FROM tickets WHERE id = %s", (sample["tickets"][1]["id"],)
        ).fetchone()
    assert incident["status"] == "analyzing"
    assert incident["severity"] == target["severity"]
    assert incident["ticket_ids"][-1] == sample["tickets"][1]["id"]
    assert ticket["status"] == "linked"


def test_existing_incident_severity_uses_max_of_old_and_current_ticket(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    target = sample["incidents"][2]

    worker(
        database_url,
        run=lambda _: ok(
            {
                "decision": "existing",
                "incident_id": target["id"],
                "confidence": 0.9,
                "reason": "같은 공격이다",
                "similar_ticket_ids": [],
            }
        ),
    ).handle(sample["tickets"][0]["id"])

    with psycopg.connect(database_url) as conn:
        severity = conn.execute(
            "SELECT severity FROM incidents WHERE id = %s", (target["id"],)
        ).fetchone()[0]
    assert severity == sample["alerts"][0]["severity"]


def test_agent_failure_creates_new_incident(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database

    worker(database_url, run=lambda _: failed("provider_error")).handle(sample["tickets"][1]["id"])

    with psycopg.connect(database_url, row_factory=psycopg.rows.dict_row) as conn:
        ticket = conn.execute(
            "SELECT * FROM tickets WHERE id = %s", (sample["tickets"][1]["id"],)
        ).fetchone()
        incident = conn.execute(
            "SELECT * FROM incidents WHERE %s = ANY(ticket_ids)",
            (sample["tickets"][1]["id"],),
        ).fetchone()
    assert ticket["details"]["l2_branch"]["decision_source"] == "rule_default"
    assert ticket["details"]["l2_branch"]["decision_fallback"] == "provider_error"
    assert incident["status"] == "analyzing"


def test_cancelled_leaves_ticket_escalated(l2_database: tuple[str, dict[str, Any]]) -> None:
    database_url, sample = l2_database

    worker(database_url, run=lambda _: failed("cancelled")).handle(sample["tickets"][1]["id"])

    with psycopg.connect(database_url) as conn:
        status = conn.execute(
            "SELECT status FROM tickets WHERE id = %s", (sample["tickets"][1]["id"],)
        ).fetchone()[0]
    assert status == "escalated"


def test_save_rechecks_ticket_state_after_model_run(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database

    def lose_race(task: Any) -> AgentResult:
        with psycopg.connect(database_url, autocommit=True) as conn:
            conn.execute("UPDATE tickets SET status = 'linked' WHERE id = %s", (task.subject_id,))
        return ok(
            {
                "decision": "new",
                "incident_id": None,
                "confidence": 0.8,
                "reason": "새 공격이다",
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
    target = sample["incidents"][1]

    def close_incident(task: Any) -> AgentResult:
        with psycopg.connect(database_url, autocommit=True) as conn:
            conn.execute("UPDATE incidents SET status = 'confirmed' WHERE id = %s", (target["id"],))
        return ok(
            {
                "decision": "existing",
                "incident_id": target["id"],
                "confidence": 0.9,
                "reason": "같은 공격이다",
                "similar_ticket_ids": [],
            }
        )

    worker(database_url, run=close_incident).handle(sample["tickets"][1]["id"])

    with psycopg.connect(database_url, row_factory=psycopg.rows.dict_row) as conn:
        ticket = conn.execute(
            "SELECT * FROM tickets WHERE id = %s", (sample["tickets"][1]["id"],)
        ).fetchone()
        incident = conn.execute(
            "SELECT * FROM incidents WHERE %s = ANY(ticket_ids)",
            (sample["tickets"][1]["id"],),
        ).fetchone()
    assert incident["id"] != target["id"]
    assert ticket["details"]["l2_branch"]["decision_fallback"] == "incident_closed"


def test_upsert_failure_does_not_rollback_postgres(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("DELETE FROM incidents")

    worker(
        database_url,
        run=lambda _: pytest.fail("후보가 없으면 모델을 부르지 않는다"),
        store=FailingUpsertStore(),
    ).handle(sample["tickets"][0]["id"])

    with psycopg.connect(database_url) as conn:
        status = conn.execute(
            "SELECT status FROM tickets WHERE id = %s", (sample["tickets"][0]["id"],)
        ).fetchone()[0]
        count = conn.execute("SELECT count(*) FROM incidents").fetchone()[0]
    assert status == "linked"
    assert count == 1


def test_worker_poll_orders_escalated_ticket_ids(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database

    found = worker(database_url, run=lambda _: failed("cancelled")).poll(1)

    assert found == [min(ticket["id"] for ticket in sample["tickets"])]


def test_vector_worker_uses_valid_linked_ticket_relationship(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    similar_ticket = sample["tickets"][0]
    current_ticket = sample["tickets"][1]
    target = sample["incidents"][0]
    with psycopg.connect(database_url) as conn:
        conn.execute(
            "UPDATE tickets SET status = 'linked' WHERE id = %s",
            (similar_ticket["id"],),
        )
    vector_store = FakeSearchStore(
        (
            SearchHit(
                similar_ticket["id"].removeprefix("tkt_"),
                0.91,
                {"incident_id": target["id"]},
            ),
        )
    )

    def choose(task: Any) -> AgentResult:
        assert task.data["candidate_source"] == "vector"
        assert task.data["candidates"][0]["similar_ticket"] == {
            "id": similar_ticket["id"],
            "title": sample["alerts"][0]["title"],
        }
        return ok(
            {
                "decision": "existing",
                "incident_id": target["id"],
                "confidence": 0.9,
                "reason": "같은 공격이다",
                "similar_ticket_ids": [similar_ticket["id"]],
            }
        )

    worker(
        database_url,
        run=choose,
        store=vector_store,
        settings=SETTINGS,
    ).handle(current_ticket["id"])

    with psycopg.connect(database_url, row_factory=psycopg.rows.dict_row) as conn:
        ticket = conn.execute(
            "SELECT * FROM tickets WHERE id = %s", (current_ticket["id"],)
        ).fetchone()
    assert ticket["details"]["l2_branch"] == {
        "candidate_source": "vector",
        "candidate_fallback": None,
        "invalid_hit_count": 0,
        "decision_source": "agent",
        "decision_fallback": None,
    }
    assert vector_store.upserts[0][2] == {"incident_id": target["id"]}


@pytest.mark.parametrize(
    ("error", "fallback"),
    [
        (CollectionMissing(), "collection_missing"),
        (StoreError(), "query_failed"),
    ],
)
def test_vector_query_failure_falls_back_to_recent(
    l2_database: tuple[str, dict[str, Any]],
    error: StoreError,
    fallback: str,
) -> None:
    database_url, sample = l2_database
    vector_store = FakeSearchStore(error=error)

    worker(
        database_url,
        run=lambda _: failed("provider_error"),
        store=vector_store,
        settings=SETTINGS,
    ).handle(sample["tickets"][1]["id"])

    with psycopg.connect(database_url, row_factory=psycopg.rows.dict_row) as conn:
        ticket = conn.execute(
            "SELECT * FROM tickets WHERE id = %s", (sample["tickets"][1]["id"],)
        ).fetchone()
    assert ticket["details"]["l2_branch"]["candidate_source"] == "recent"
    assert ticket["details"]["l2_branch"]["candidate_fallback"] == fallback


def test_empty_embedding_text_uses_recent_without_indexing(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    ticket_id = sample["tickets"][0]["id"]
    vector_store = FakeSearchStore()
    with psycopg.connect(database_url) as conn:
        conn.execute("DELETE FROM incidents")
        conn.execute(
            "UPDATE alerts SET title = '' WHERE id = %s",
            (sample["alerts"][0]["id"],),
        )
        conn.execute("UPDATE tickets SET verdict = NULL WHERE id = %s", (ticket_id,))

    worker(
        database_url,
        run=lambda _: pytest.fail("후보가 없으면 모델을 부르지 않는다"),
        store=vector_store,
        settings=SETTINGS,
    ).handle(ticket_id)

    with psycopg.connect(database_url, row_factory=psycopg.rows.dict_row) as conn:
        ticket = conn.execute("SELECT * FROM tickets WHERE id = %s", (ticket_id,)).fetchone()
    assert ticket["details"]["l2_branch"]["candidate_source"] == "recent"
    assert ticket["details"]["l2_branch"]["candidate_fallback"] == "empty_text"
    assert vector_store.upserts == []


def test_invalid_vector_hit_count_is_recorded_before_recent_fallback(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    vector_store = FakeSearchStore(
        (SearchHit("bad-point", 0.99, {"incident_id": sample["incidents"][0]["id"]}),)
    )

    worker(
        database_url,
        run=lambda _: failed("provider_error"),
        store=vector_store,
        settings=SETTINGS,
    ).handle(sample["tickets"][1]["id"])

    with psycopg.connect(database_url, row_factory=psycopg.rows.dict_row) as conn:
        ticket = conn.execute(
            "SELECT * FROM tickets WHERE id = %s", (sample["tickets"][1]["id"],)
        ).fetchone()
    assert ticket["details"]["l2_branch"]["candidate_fallback"] == "no_valid_candidates"
    assert ticket["details"]["l2_branch"]["invalid_hit_count"] == 1


def test_reindex_ensures_collection_and_indexes_consistent_linked_ticket(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    ticket_id = sample["tickets"][0]["id"]
    incident_id = sample["incidents"][0]["id"]
    with psycopg.connect(database_url) as conn:
        conn.execute("DELETE FROM incidents WHERE id <> %s", (incident_id,))
        conn.execute("UPDATE tickets SET status = 'linked' WHERE id = %s", (ticket_id,))
    vector_store = FakeStore()

    result = reindex(database_url, FakeEmbedder(), vector_store)

    assert result == {"processed": 1, "succeeded": 1, "failed": 0}
    assert vector_store.ensured == 1
    assert vector_store.upserts == [
        (
            ticket_id.removeprefix("tkt_"),
            [1.0, 0.0],
            {"incident_id": incident_id},
        )
    ]


def test_reindex_counts_multiple_incident_membership_as_failure(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    ticket_id = sample["tickets"][0]["id"]
    with psycopg.connect(database_url) as conn:
        conn.execute("UPDATE tickets SET status = 'linked' WHERE id = %s", (ticket_id,))
    vector_store = FakeStore()

    result = reindex(database_url, FakeEmbedder(), vector_store, recreate=True)

    assert result == {"processed": 1, "succeeded": 0, "failed": 1}
    assert vector_store.dropped == 1
    assert vector_store.ensured == 1
    assert vector_store.upserts == []


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
        proposals = conn.execute("SELECT * FROM incident_proposals ORDER BY kind, seq").fetchall()
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
    assert [(row["kind"], row["seq"], row["body"]) for row in proposals] == [
        ("detection_rule", 1, analysis["detection_rules"][0]),
        ("response_action", 1, analysis["response_actions"][0]),
    ]


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
    assert artifact_count == 0


def test_analyze_worker_marks_round_limit_once_and_then_stops_polling(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    incident_id = prepare_analyzing_incident(database_url, sample, analysis_round=5)
    analyzer = analyze_worker(database_url, lambda _: pytest.fail("한도에서 모델을 부르면 안 된다"))

    assert incident_id in analyzer.poll(10)
    analyzer.handle(incident_id)

    assert incident_id not in analyzer.poll(10)
    with psycopg.connect(database_url) as conn:
        details = conn.execute(
            "SELECT details FROM incidents WHERE id = %s", (incident_id,)
        ).fetchone()[0]
    assert details["l2_analyze"]["stopped"] == "round_limit"


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
