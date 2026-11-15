"""L2 Ticket 그래프 연결 규칙을 작은 손 작성 fixture로 확인한다."""

import json
from pathlib import Path

import soc.l2.branch.graph as graph
from soc.l2.branch.graph import classify_graph

FIXTURE = Path(__file__).parent / "fixtures" / "l2" / "graph.json"


def sample() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_graph_links_tickets_through_normalized_alert_entity() -> None:
    data = sample()

    result = classify_graph(data["ticket_id"], data["source"], data["matches"], max_candidates=5)

    assert result.coverage == "complete"
    assert [item.incident_id for item in result.candidates] == [
        "inc_01a19f93-1150-7000-8000-000000000201"
    ]
    path = result.candidates[0].paths[0]
    assert [node["kind"] for node in path["nodes"]] == [
        "ticket",
        "alert",
        "entity",
        "alert",
        "ticket",
        "incident",
    ]
    assert path["nodes"][2]["value"] == "ws-07"


def test_event_nodes_do_not_connect_ticket_graph() -> None:
    data = sample()

    result = classify_graph(data["ticket_id"], data["source"], data["matches"], max_candidates=5)

    assert all(
        item.incident_id != "inc_01a19f93-1150-7000-8000-000000000203" for item in result.candidates
    )


def test_no_path_is_complete_and_has_no_candidates() -> None:
    data = sample()

    result = classify_graph(data["ticket_id"], data["source"], [], max_candidates=5)

    assert result.coverage == "complete"
    assert result.reason == "no_path"
    assert result.candidates == ()


def test_candidate_limit_makes_coverage_incomplete() -> None:
    data = sample()
    second = {
        **data["matches"][0],
        "incident_id": "inc_01a19f93-1150-7000-8000-000000000205",
    }

    result = classify_graph(
        data["ticket_id"], data["source"], [data["matches"][0], second], max_candidates=1
    )

    assert result.coverage == "incomplete"
    assert result.reason == "candidate_limit"
    assert result.candidates == ()


def test_public_ip_only_path_does_not_match_incident(monkeypatch) -> None:
    data = sample()
    source = {**data["source"], "entities": [data["source"]["entities"][1]]}
    match = {**data["matches"][0], "entities": [data["matches"][0]["entities"][1]]}
    monkeypatch.setattr(graph, "_is_public_ip", lambda _: True)

    result = classify_graph(data["ticket_id"], source, [match], max_candidates=5)

    assert result.coverage == "complete"
    assert result.reason == "public_ip_only"
    assert result.candidates == ()
    assert result.paths == ()


def test_l3_hunt_is_the_graph_start_node() -> None:
    data = sample()
    source = {**data["source"], "kind": "hunt", "id": "hnt_01a19f93-1150-7000-8000-000000000201"}

    result = classify_graph(data["ticket_id"], source, [data["matches"][0]], max_candidates=5)

    assert result.candidates[0].paths[0]["nodes"][1] == {
        "id": source["id"],
        "kind": "hunt",
    }
