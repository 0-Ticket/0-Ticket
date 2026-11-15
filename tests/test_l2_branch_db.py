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
from soc.agent.compose import compose_instructions
from soc.agent.llm import input_chars
from soc.agent.runner import wrap_data
from soc.asset_lookup import AssetLookupError
from soc.contracts import to_datetime
from soc.db.migrate import MIGRATIONS_DIR, migrate
from soc.l2.analyze import context as analyze_context
from soc.l2.analyze.tasks import make_investigate_task
from soc.l2.analyze.worker import L2AnalyzeWorker
from soc.l2.branch import build_branch
from soc.l2.branch.read import read_branch_data
from soc.l2.branch.worker import L2BranchWorker
from soc.l2.config import AnalyzeSettings, BranchSettings

pytestmark = pytest.mark.db

FIXTURE = Path(__file__).parent / "fixtures" / "l2" / "branch.json"
SETTINGS = BranchSettings(
    candidate_window_ms=86_400_000,
    max_candidates=5,
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
    }
    values.update(overrides)
    return BranchSettings(**values)


def worker(
    database_url: str,
    *,
    run: Any,
    settings: BranchSettings | None = None,
) -> L2BranchWorker:
    return L2BranchWorker(
        database_url,
        settings or recent_settings(),
        run=run,
        clock=lambda: to_datetime(1793764800000),
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
    assert ticket["details"]["l2_branch"] == {
        "coverage": "complete",
        "reason": "no_path",
        "paths": [],
        "decision_source": "graph_default",
        "decision_fallback": "no_path",
    }
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


def test_public_ip_only_path_creates_new_incident(
    l2_database: tuple[str, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    import soc.l2.branch.graph as graph

    database_url, sample = l2_database
    target_id = prepare_graph_candidate(database_url, sample)
    current_id = sample["tickets"][1]["id"]
    ip_entity = {"type": "ip", "value": "192.0.2.7", "role": "target"}
    with psycopg.connect(database_url) as conn:
        conn.execute(
            "UPDATE hunts SET entities = %s WHERE id = %s",
            (Jsonb([ip_entity]), sample["hunts"][0]["id"]),
        )
        conn.execute(
            "UPDATE alerts SET entities = %s WHERE id = %s",
            (Jsonb([ip_entity]), sample["alerts"][0]["id"]),
        )
    monkeypatch.setattr(graph, "_is_public_ip", lambda _: True)

    worker(database_url, run=lambda _: pytest.fail("?? IP? ??? ??? ??? ???")).handle(current_id)

    with psycopg.connect(database_url, row_factory=psycopg.rows.dict_row) as conn:
        ticket = conn.execute("SELECT * FROM tickets WHERE id = %s", (current_id,)).fetchone()
        target = conn.execute("SELECT * FROM incidents WHERE id = %s", (target_id,)).fetchone()
    assert ticket["details"]["l2_branch"]["reason"] == "public_ip_only"
    assert current_id not in target["ticket_ids"]


def test_candidate_limit_is_saved_as_incomplete_and_creates_new_incident(
    l2_database: tuple[str, dict[str, Any]],
) -> None:
    database_url, sample = l2_database
    prepare_graph_candidate(database_url, sample, duplicate_candidate=True)
    settings = BranchSettings(candidate_window_ms=86_400_000, max_candidates=1)
    current_id = sample["tickets"][1]["id"]

    worker(
        database_url, run=lambda _: pytest.fail("coverage ???? ??? ??? ???"), settings=settings
    ).handle(current_id)

    with psycopg.connect(database_url, row_factory=psycopg.rows.dict_row) as conn:
        ticket = conn.execute("SELECT * FROM tickets WHERE id = %s", (current_id,)).fetchone()
    branch = ticket["details"]["l2_branch"]
    assert branch["coverage"] == "incomplete"
    assert branch["reason"] == "candidate_limit"
    assert branch["decision_fallback"] == "candidate_limit"


def test_agent_failure_creates_new_incident_when_graph_candidate_exists(
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
    assert ticket["details"]["l2_branch"]["decision_source"] == "rule_default"
    assert ticket["details"]["l2_branch"]["decision_fallback"] == "provider_error"
    assert incident["status"] == "analyzing"


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
    assert incident["id"] != target_id
    assert ticket["details"]["l2_branch"]["decision_fallback"] == "incident_closed"


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
