"""손제작 시나리오의 엔티티 경로를 L2 그래프 조회로 검증한다(db 마커).

Ticket 유사도 후보의 전체 분류는 test_l2_branch_db.py에서 검증한다.
"""

from types import SimpleNamespace
from typing import Any

import psycopg
import pytest
from conftest import HiddenUrl
from scenario_support import CASES, NOW, Built, build_case

from soc.agent import AgentResult
from soc.contracts import to_datetime
from soc.db.migrate import migrate
from soc.l2.branch import build_branch
from soc.l2.branch.candidates import VectorCandidate
from soc.l2.branch.graph import read_graph
from soc.l2.branch.worker import L2BranchWorker
from soc.l2.config import BranchSettings

pytestmark = pytest.mark.db


def params() -> list[Any]:
    return [pytest.param(case, id=case["case"]) for case in CASES]


def graph_for(conn: psycopg.Connection, built: Built):
    context = build_branch(conn, built.current_ticket_id)
    sources = tuple(
        {"kind": "alert", "id": alert["details"]["id"], "entities": alert["details"]["entities"]}
        for alert in context.alerts
    )
    if not sources and context.hunt is not None:
        sources = (
            {"kind": "hunt", "id": context.hunt["id"], "entities": context.hunt["entities"]},
        )
    return read_graph(
        conn,
        built.current_ticket_id,
        sources,
        to_datetime(NOW),
        candidate_window_ms=86_400_000,
        max_candidates=5,
        max_incident_tickets=10,
        incident_ids=tuple(built.incidents.values()),
    )


@pytest.mark.parametrize("case", params())
def test_scenario_matches_the_graph_rules(
    temp_database: HiddenUrl, case: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    migrate(temp_database)
    with psycopg.connect(temp_database, autocommit=True) as conn:
        built = build_case(conn, case)
        graph = graph_for(conn, built)
    names = {incident_id: name for name, incident_id in built.incidents.items()}
    candidates = [names[c.incident_id] for c in graph.candidates]
    expect = case["expect"]
    assert graph.coverage == "complete"
    if case["case"] == "6b-candidate-limit":
        assert len(candidates) > 5
        assert graph.reason == "paths_found"
    else:
        assert graph.reason == expect["reason"]
        assert candidates == expect["candidates"]
    assert bool(graph.paths) == bool(candidates)

    vectors = tuple(
        VectorCandidate(
            candidate.incident,
            candidate.incident["ticket_ids"][0],
            0.9,
            candidate.target_hosts,
        )
        for candidate in graph.candidates
    )
    calls = []

    def fake_run(task):
        calls.append(task)
        return AgentResult(
            ok=True,
            output={
                "decision": "new",
                "incident_id": None,
                "confidence": 0.9,
                "reason": "손제작 테스트 판단",
                "similar_ticket_ids": [],
            },
            failure=None,
            detail=None,
            run_id="run_01a19f93-1150-7000-8000-000000000601",
        )

    monkeypatch.setattr("soc.l2.branch.worker.index_ready", lambda *_: True)
    monkeypatch.setattr("soc.l2.branch.worker.find_candidates", lambda *_args, **_kwargs: vectors)
    L2BranchWorker(
        temp_database,
        BranchSettings(86_400_000, 5, 10),
        run=fake_run,
        clock=lambda: to_datetime(NOW),
        service=SimpleNamespace(),
    ).handle(built.current_ticket_id)
    with psycopg.connect(temp_database) as conn:
        status, details = conn.execute(
            "SELECT status, details->'l2_branch' FROM tickets WHERE id = %s",
            (built.current_ticket_id,),
        ).fetchone()
        joined = conn.execute(
            "SELECT id FROM incidents WHERE %s = ANY(ticket_ids)", (built.current_ticket_id,)
        ).fetchone()[0]
    assert status == "linked"
    assert joined not in built.incidents.values()
    assert [
        names[item["incident_id"]] for task in calls for item in task.data["candidates"]
    ] == candidates
    assert bool(calls) == bool(candidates)
    assert details["coverage"] == "complete"
    assert details["reason"] == ("paths_found" if candidates else "no_similar_candidate")
    assert details["decision_fallback"] == (None if candidates else "no_similar_candidate")


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("5-same-local-ip-different-environments", ["111111111111", "i-0aaaaaaaaaaaaaaaa"]),
        ("5b-same-local-ip-same-environment", ["111111111111", "i-0aaaaaaaaaaaaaaaa"]),
        ("5c-same-public-src-different-environments", ["111111111111", "i-0aaaaaaaaaaaaaaaa"]),
        ("1a-same-source-same-src-ip", None),
    ],
)
def test_candidate_input_carries_the_path_alerts_target_hosts(
    temp_database: HiddenUrl, name: str, expected: list[str] | None
) -> None:
    case = next(item for item in CASES if item["case"] == name)
    migrate(temp_database)
    with psycopg.connect(temp_database, autocommit=True) as conn:
        built = build_case(conn, case)
        graph = graph_for(conn, built)
    hosts = list(graph.candidates[0].target_hosts)
    assert hosts == (expected or [])
