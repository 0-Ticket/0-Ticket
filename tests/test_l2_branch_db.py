"""L2 분류 입력을 PostgreSQL에서 읽는 경계를 확인한다(db 마커)."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb

from soc.contracts import to_datetime
from soc.db.migrate import migrate
from soc.l2.branch import build_branch
from soc.l2.branch.read import _OPEN_INCIDENTS_QUERY, read_branch_data
from soc.l2.config import BranchSettings

pytestmark = pytest.mark.db

FIXTURE = Path(__file__).parent / "fixtures" / "l2" / "branch.json"
SETTINGS = BranchSettings(
    candidate_window_ms=86_400_000,
    max_candidates=5,
    strong_signal_types=frozenset({"file_hash", "process", "url", "domain", "user"}),
    weak_signal_types=frozenset({"ip", "host"}),
    shared_entity_values=("shared-proxy",),
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


def test_reads_ticket_evidence_and_only_open_recent_incidents(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    with psycopg.connect(database_url) as conn:
        rows = read_branch_data(
            conn,
            sample["tickets"][0]["id"],
            sample_now(sample),
            SETTINGS.candidate_window_ms,
        )

    assert [row["id"] for row in rows.alerts] == [sample["alerts"][0]["id"]]
    assert [row["id"] for row in rows.events] == [sample["events"][0]["id"]]
    assert rows.evidence_ids == (
        sample["alerts"][0]["id"],
        sample["events"][0]["id"],
        sample["agent_logs"][0]["id"],
    )
    assert rows.missing_evidence_count == 1
    assert {row["id"] for row in rows.incidents} == {
        sample["incidents"][0]["id"],
        sample["incidents"][1]["id"],
        sample["incidents"][2]["id"],
    }


def test_l3_ticket_reads_hunt_evidence_and_builds_ranked_result(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    with psycopg.connect(database_url) as conn:
        result = build_branch(conn, sample["tickets"][1]["id"], sample_now(sample), SETTINGS)

    assert result.context.alerts == ()
    assert result.context.hunt == sample["hunts"][0]
    assert [event["id"] for event in result.context.events] == [sample["events"][1]["id"]]
    assert result.context.missing_evidence_count == 1
    assert ("domain", "beacon.example") in {signal.key for signal in result.context.signals}


def test_non_escalated_ticket_is_rejected(l2_database: tuple[str, dict[str, Any]]) -> None:
    database_url, sample = l2_database
    with psycopg.connect(database_url) as conn:
        conn.execute(
            "UPDATE tickets SET status = 'linked' WHERE id = %s", (sample["tickets"][0]["id"],)
        )
        with pytest.raises(ValueError, match="escalated"):
            read_branch_data(
                conn,
                sample["tickets"][0]["id"],
                sample_now(sample),
                SETTINGS.candidate_window_ms,
            )


def test_open_incident_query_uses_status_index(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    now = sample_now(sample)
    cutoff = to_datetime(sample["now"] - SETTINGS.candidate_window_ms)
    with psycopg.connect(database_url) as conn:
        conn.execute("SET enable_seqscan = off")
        rows = conn.execute(
            "EXPLAIN " + _OPEN_INCIDENTS_QUERY,
            (["analyzing", "awaiting_review", "human_handling"], cutoff, now),
        ).fetchall()

    plan = "\n".join(row[0] for row in rows)
    assert "incidents_status_idx" in plan, plan
