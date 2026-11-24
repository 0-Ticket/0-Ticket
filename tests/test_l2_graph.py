"""L2 Ticket 그래프 연결 규칙을 작은 손 작성 fixture로 확인한다."""

import ipaddress
import json
from pathlib import Path

import pytest

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
    assert path["nodes"][2]["value"] == "192.0.2.7"
    assert len(result.paths) == 1


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


def test_candidate_count_does_not_discard_graph_paths() -> None:
    data = sample()
    second = {
        **data["matches"][0],
        "incident_id": "inc_01a19f93-1150-7000-8000-000000000205",
    }

    result = classify_graph(
        data["ticket_id"], data["source"], [data["matches"][0], second], max_candidates=1
    )

    assert result.coverage == "complete"
    assert result.reason == "paths_found"
    assert len(result.candidates) == 2


def test_public_src_ip_alone_connects_tickets() -> None:
    data = sample()
    public_ip = "8.8.8.8"
    assert ipaddress.ip_address(public_ip).is_global
    source = {
        **data["source"],
        "entities": [{**data["source"]["entities"][1], "value": public_ip}],
    }
    match = {
        **data["matches"][0],
        "entities": [{**data["matches"][0]["entities"][1], "value": public_ip}],
    }

    result = classify_graph(data["ticket_id"], source, [match], max_candidates=5)

    assert result.coverage == "complete"
    assert result.reason == "paths_found"
    assert len(result.candidates) == 1
    assert result.paths[0]["nodes"][2]["value"] == public_ip


@pytest.mark.parametrize("role", [None, "dst", "target", "actor"])
def test_non_src_entities_do_not_connect_tickets(role: str | None) -> None:
    data = sample()
    entity = {"type": "host", "value": "shared-collector", "role": role}
    source = {**data["source"], "entities": [entity]}
    match = {**data["matches"][0], "entities": [entity]}

    result = classify_graph(data["ticket_id"], source, [match], max_candidates=5)

    assert result.reason == "no_path"
    assert result.candidates == ()


@pytest.mark.parametrize("source_role, peer_role", [("src", "dst"), ("dst", "src")])
def test_both_sides_must_be_src(source_role: str, peer_role: str) -> None:
    data = sample()
    source = {
        **data["source"],
        "entities": [{"type": "ip", "value": "192.0.2.7", "role": source_role}],
    }
    match = {
        **data["matches"][0],
        "entities": [{"type": "ip", "value": "192.0.2.7", "role": peer_role}],
    }

    result = classify_graph(data["ticket_id"], source, [match], max_candidates=5)

    assert result.reason == "no_path"
    assert result.candidates == ()


def test_other_role_does_not_overwrite_src_for_same_value() -> None:
    data = sample()
    source = {
        **data["source"],
        "entities": [
            {"type": "ip", "value": "192.0.2.7", "role": "src"},
            {"type": "ip", "value": "192.0.2.7", "role": "dst"},
        ],
    }
    match = {**data["matches"][0], "entities": [data["matches"][0]["entities"][1]]}

    result = classify_graph(data["ticket_id"], source, [match], max_candidates=5)

    assert result.reason == "paths_found"
    assert len(result.paths) == 1


def test_l3_hunt_is_the_graph_start_node() -> None:
    data = sample()
    source = {**data["source"], "kind": "hunt", "id": "hnt_01a19f93-1150-7000-8000-000000000201"}

    result = classify_graph(data["ticket_id"], source, [data["matches"][0]], max_candidates=5)

    assert result.candidates[0].paths[0]["nodes"][1] == {
        "id": source["id"],
        "kind": "hunt",
    }


def test_l3_hunt_non_src_entity_does_not_connect() -> None:
    data = sample()
    source = {
        **data["source"],
        "kind": "hunt",
        "entities": [{"type": "host", "value": "shared-collector", "role": "target"}],
    }
    match = {**data["matches"][0], "entities": [data["matches"][0]["entities"][0]]}

    result = classify_graph(data["ticket_id"], source, [match], max_candidates=5)

    assert result.candidates == ()


def _host(value: str) -> dict:
    return {"type": "host", "value": value, "role": "target"}


def test_target_hosts_come_from_the_alert_entities_of_path_matches() -> None:
    data = sample()
    match = {
        **data["matches"][0],
        "alert_entities": [
            _host("111111111111"),
            _host("I-0AAAA"),
            _host(" i-0aaaa "),
            {"type": "host", "value": "shared-collector", "role": None},
            {"type": "host", "value": "web-01", "role": "src"},
            {"type": "ip", "value": "192.0.2.7", "role": "src"},
        ],
    }

    result = classify_graph(data["ticket_id"], data["source"], [match], max_candidates=5)

    assert result.candidates[0].target_hosts == ("111111111111", "i-0aaaa")


def test_target_hosts_are_empty_without_alert_entities() -> None:
    data = sample()

    result = classify_graph(data["ticket_id"], data["source"], data["matches"], max_candidates=5)

    assert result.candidates[0].target_hosts == ()


def test_target_hosts_are_capped_after_sorting() -> None:
    data = sample()
    match = {
        **data["matches"][0],
        "alert_entities": [_host(f"h-{number:02d}") for number in reversed(range(15))],
    }

    result = classify_graph(data["ticket_id"], data["source"], [match], max_candidates=5)

    assert result.candidates[0].target_hosts == tuple(f"h-{number:02d}" for number in range(10))


def test_target_hosts_merge_matches_of_the_same_incident_only() -> None:
    data = sample()
    first = {**data["matches"][0], "alert_entities": [_host("acct-a")]}
    second = {
        **data["matches"][0],
        "id": "alt_01a19f93-1150-7000-8000-000000000299",
        "alert_entities": [_host("acct-b")],
    }
    other = {
        **data["matches"][0],
        "incident_id": "inc_01a19f93-1150-7000-8000-000000000205",
        "alert_entities": [_host("acct-c")],
    }

    result = classify_graph(
        data["ticket_id"], data["source"], [first, second, other], max_candidates=5
    )

    by_incident = {item.incident_id: item.target_hosts for item in result.candidates}
    assert by_incident == {
        "inc_01a19f93-1150-7000-8000-000000000201": ("acct-a", "acct-b"),
        "inc_01a19f93-1150-7000-8000-000000000205": ("acct-c",),
    }
