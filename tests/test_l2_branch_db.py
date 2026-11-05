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
from soc.contracts import to_datetime
from soc.db.migrate import migrate
from soc.l2.branch import build_branch
from soc.l2.branch.read import (
    _RECENT_INCIDENTS_QUERY,
    read_branch_data,
    read_hit_tickets,
    read_incidents_by_ids,
    read_recent_incidents,
)
from soc.l2.branch.worker import L2BranchWorker
from soc.l2.config import BranchSettings
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
