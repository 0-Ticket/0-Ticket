"""L2 조사 입력의 그래프 요약과 입력 크기를 손으로 만든 샘플과 합성 입력으로 확인한다(#396)."""

import json
import tomllib
from pathlib import Path
from typing import Any

from soc.agent.compose import compose_instructions
from soc.agent.llm import input_chars
from soc.agent.runner import wrap_data
from soc.entities import normalize_entity_value
from soc.l2.analyze.context import (
    MAX_PEER_IDS,
    AnalyzeContext,
    summarize_paths,
    ticket_graph,
)
from soc.l2.analyze.tasks import make_investigate_task
from soc.l2.branch.graph import classify_graph

FIXTURE = Path(__file__).parent / "fixtures" / "l2" / "path_summary.json"
CONFIG = Path(__file__).parents[1] / "config" / "default.toml"
# Alert ocsf는 서버에서 Incident당 약 13,000자까지다. Event는 재지 못해 같은 값으로 잡는다(#396)
ALERT_CHARS = 13_000
EVENT_CHARS = 13_000
FAILURES = 110  # 서버에서 가장 큰 Incident의 누적 실패 기록 수
INC = "inc_01a19f93-1150-7000-8000-0000000000aa"


def sample() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def sample_paths() -> tuple[dict[str, Any], ...]:
    data = sample()
    return classify_graph(
        data["ticket_id"], data["sources"], data["matches"], max_candidates=5
    ).paths


def uid(prefix: str, number: int) -> str:
    return f"{prefix}_01a19f93-1150-7000-8000-{number:012d}"


def entity_ids(item: dict[str, Any]) -> set[str]:
    return {
        f"{e['type']}:{normalize_entity_value(e['type'], e['value'])}"
        for e in item["entities"]
        if e["role"] == "src"
    }


def test_links_group_by_entity_with_alert_and_hunt_ids() -> None:
    links, peers = summarize_paths(sample_paths())

    by_entity = {link["entity"]: link for link in links}
    assert sorted(by_entity) == ["ip:192.0.2.7", "ip:192.0.2.9"]
    seven, nine = by_entity["ip:192.0.2.7"], by_entity["ip:192.0.2.9"]
    # 출발이 Hunt인 경로도 같은 형식이다
    assert sorted(seven["from"]) == [uid("alt", 301), uid("hnt", 301)]
    assert {k: sorted(v) for k, v in seven["to"].items()} == {
        uid("tkt", 311): [uid("alt", 311), uid("alt", 312)],
        uid("tkt", 313): [uid("alt", 314)],
    }
    # 상대가 Hunt인 경로도 같은 형식이다
    assert nine["from"] == [uid("alt", 301)]
    assert {k: sorted(v) for k, v in nine["to"].items()} == {
        uid("tkt", 311): [uid("alt", 312)],
        uid("tkt", 312): [uid("hnt", 313)],
    }
    assert peers == {
        uid("tkt", 311): "inc_01a19f93-1150-7000-8000-0000000003a0",
        uid("tkt", 312): "inc_01a19f93-1150-7000-8000-0000000003b0",
        uid("tkt", 313): "inc_01a19f93-1150-7000-8000-0000000003b0",
    }
    assert all("omitted" not in link for link in links)
    text = json.dumps(links)
    assert "nodes" not in text and "edges" not in text


def test_truncated_paths_do_not_invent_connections() -> None:
    data = sample()
    holders = {s["id"]: entity_ids(s) for s in data["sources"]}
    holders |= {m["id"]: entity_ids(m) for m in data["matches"]}
    paths = sample_paths()
    assert len(paths) >= 6

    for keep in range(1, len(paths) + 1):
        kept = paths[:keep]
        links, peers = summarize_paths(kept)
        real = {  # 남은 경로가 실제로 가진 (엔티티, 출발, 상대 Ticket, 상대 ID, Incident)
            (p["nodes"][2]["id"], p["nodes"][1]["id"], p["ticket_id"], p["nodes"][3]["id"])
            for p in kept
        }
        assert len({link["entity"] for link in links}) == len(links)
        assert peers == {p["ticket_id"]: p["incident_id"] for p in kept}
        for link in links:
            entity = link["entity"]
            for source in link["from"]:
                assert any(r[0] == entity and r[1] == source for r in real)
                assert entity in holders[source]
            for ticket, ids in link["to"].items():
                for peer in ids:
                    assert any(r[0] == entity and r[2:] == (ticket, peer) for r in real)
                    assert entity in holders[peer]


def test_peer_ids_over_the_limit_are_counted_not_listed() -> None:
    source = {
        "kind": "alert",
        "id": uid("alt", 1),
        "entities": [{"type": "ip", "value": "192.0.2.7", "role": "src"}],
    }
    entity = [{"type": "ip", "value": "192.0.2.7", "role": "src"}]
    matches = [
        {
            "incident_id": INC,
            "ticket_id": uid("tkt", 50 + (n % 2)),
            "kind": "alert",
            "id": uid("alt", 100 + n),
            "entities": entity,
        }
        for n in range(8)
    ]
    paths = classify_graph(uid("tkt", 1), source, matches, max_candidates=5).paths

    links, peers = summarize_paths(paths, max_peer_ids=3)
    full, _ = summarize_paths(paths, max_peer_ids=100)

    assert len(links) == 1 and links[0]["from"] == [uid("alt", 1)]
    # 연결(엔티티 → 상대 Ticket)과 Incident는 하나도 빠지지 않는다
    assert set(links[0]["to"]) == set(full[0]["to"]) == {uid("tkt", 50), uid("tkt", 51)}
    assert peers == {uid("tkt", 50): INC, uid("tkt", 51): INC}
    for ticket, ids in links[0]["to"].items():
        assert ids == full[0]["to"][ticket][:3]
        assert links[0]["omitted"][ticket] == len(full[0]["to"][ticket]) - 3
    assert MAX_PEER_IDS >= 1


def test_ticket_graph_keeps_coverage_and_reason_and_marks_legacy() -> None:
    peers: dict[str, str] = {}
    branch = {"coverage": "incomplete", "reason": "candidate_limit", "paths": sample_paths()[:2]}
    ticket = {"id": uid("tkt", 301), "details": {"l2_branch": branch}}

    graph = ticket_graph(ticket, peers)

    assert set(graph) == {"ticket_id", "coverage", "reason", "links"}
    assert (graph["coverage"], graph["reason"]) == ("incomplete", "candidate_limit")
    assert graph["links"] and peers

    legacy = ticket_graph({"id": uid("tkt", 9), "details": {}}, {})
    assert legacy == {"ticket_id": uid("tkt", 9), "coverage": "legacy", "reason": None, "links": []}


def hand_ticket(index: int, branch: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": uid("tkt", index),
        "title": "합성 Ticket",
        "origin": "auto",
        "status": "linked",
        "alert_ids": [uid("alt", index)],
        "hunt_id": None,
        "entities": [{"type": "ip", "value": "203.0.113.1", "role": "src"}],
        "verdict": {"decision": "malicious", "confidence": 0.9, "reason": "합성"},
        "details": {"l2_branch": branch},
    }


def build_context(
    shapes: list[tuple[list[dict[str, Any]], list[dict[str, Any]]]],
) -> AnalyzeContext:
    """shapes[i] = (Ticket i+1의 출발 엔티티, 상대 노드 목록)으로 Incident 하나를 합성한다."""
    rows, graphs, peers = [], [], {}
    snapshot = [{"incident_id": INC, "ticket_id": uid("tkt", 1), "score": 0.9, "updated_at": 1}] * 5
    for index, (entities, matches) in enumerate(shapes, start=1):
        source = {"kind": "alert", "id": uid("alt", index), "entities": entities}
        found = classify_graph(uid("tkt", index), source, matches, max_candidates=5)
        branch = {
            "coverage": "complete",
            "reason": "paths_found",
            "paths": list(found.paths[:50]),
            "candidates": snapshot,
            "snapshot": snapshot,
            "progress": {"phase": "initial", "pool": [INC] * 5, "cursor": 5, "winners": [INC]},
            "failures": 0,
        }
        ticket = hand_ticket(index, branch)
        rows.append(ticket)
        graphs.append(ticket_graph(ticket, peers))
    failures = [
        {"attempt": n, "failure": "budget_exceeded", "run_id": uid("run", n)}
        for n in range(FAILURES)
    ]
    return AnalyzeContext(
        incident={
            "id": INC,
            "title": "합성",
            "status": "analyzing",
            "ticket_ids": [t["id"] for t in rows],
            "details": {"l2_analyze": {"failures": failures, "failure_streak": 3}},
        },
        tickets=tuple(rows),
        alerts=({"id": uid("alt", 9998), "pad": "a" * ALERT_CHARS},),
        events=({"id": uid("evt", 9999), "pad": "e" * EVENT_CHARS},),
        hunts=(),
        assets=[],
        ticket_graphs=tuple(graphs),
        window={"from": 0, "to": 1},
        previous_artifact=None,
        rejection=None,
        evidence_ids=(),
        asset_lookup_failed=False,
        max_range_days=7,
        peer_tickets=peers,
    )


def ip(value: int) -> dict[str, str]:
    return {"type": "ip", "value": f"203.0.113.{value}", "role": "src"}


def server_shape(paths_total: int, *, tickets: int = 10) -> list[Any]:
    """서버에서 가장 큰 Incident의 구조: 엔티티 1개, Ticket 10개, 상대 21개(경로 131개).

    상대 Ticket마다 Alert가 하나다. 경로 수에 비례해 상대 수를 21/131로 늘려 같은 구조로 키운다.
    """
    pool = max(1, round(paths_total * 21 / 131))
    shapes = []
    for index in range(tickets):
        count = paths_total // tickets + (1 if index < paths_total % tickets else 0)
        matches = [
            {
                "incident_id": uid("inc", 900 + peer % 3),
                "ticket_id": uid("tkt", 2000 + peer),
                "kind": "alert",
                "id": uid("alt", 5000 + peer),
                "entities": [ip(1)],
            }
            for peer in ((index * count + step) % pool for step in range(count))
        ]
        shapes.append(([ip(1)], matches))
    return shapes


def worst_shape() -> list[Any]:
    """Ticket 10개 × 경로 50개. 엔티티·상대 Ticket·상대 Alert가 경로마다 모두 다르다."""
    return [
        (
            [ip(k) for k in range(1, 51)],
            [
                {
                    "incident_id": uid("inc", 900 + n % 5),
                    "ticket_id": uid("tkt", 2000 + index * 100 + n),
                    "kind": "alert",
                    "id": uid("alt", 5000 + index * 100 + n),
                    "entities": [ip(n + 1)],
                }
                for n in range(50)
            ],
        )
        for index in range(1, 11)
    ]


def total_chars(data: dict[str, Any]) -> int:
    task = make_investigate_task(INC, attempt=1, data=data, allowed_evidence_ids=())
    return input_chars(
        compose_instructions(task, max_turns=12), [{"role": "user", "content": wrap_data(data)}]
    )


def key_chars(data: dict[str, Any]) -> dict[str, int]:
    return {key: len(json.dumps(value, ensure_ascii=False)) for key, value in data.items()}


def limit() -> int:
    return tomllib.loads(CONFIG.read_text(encoding="utf-8"))["agent"]["l2"]["max_input_chars"]


def before_data(context: AnalyzeContext) -> dict[str, Any]:
    """변경 전 입력 모양: details가 그대로 있고 graph에 저장 경로가 한 번 더 들어간다."""
    data = context.investigate_data()
    graph = [
        {
            "ticket_id": g["ticket_id"],
            "coverage": g["coverage"],
            "reason": g["reason"],
            "paths": t["details"]["l2_branch"]["paths"],
        }
        for g, t in zip(context.ticket_graphs, context.tickets, strict=True)
    ]
    return {
        **data,
        "incident": context.incident,
        "tickets": list(context.tickets),
        "graph": {"tickets": graph},
    }


def test_investigate_input_has_no_details_and_no_raw_paths() -> None:
    data = build_context(server_shape(131)).investigate_data()

    assert all("details" not in ticket for ticket in data["tickets"])
    assert "details" not in data["incident"]
    text = json.dumps(data)
    assert '"paths"' not in text and '"nodes"' not in text and '"edges"' not in text
    assert "l2_branch" not in text and "failures" not in text
    assert [g["ticket_id"] for g in data["graph"]["tickets"]] == [t["id"] for t in data["tickets"]]
    assert all(g["coverage"] == "complete" for g in data["graph"]["tickets"])
    assert data["graph"]["peer_tickets"]


def test_largest_server_structure_fits_the_l2_input_limit() -> None:
    context = build_context(server_shape(131))
    data = context.investigate_data()

    # 서버 구조 확인: 경로 131, 엔티티 1, (출발 Ticket, 엔티티) 10, 상대 Ticket·Alert 21
    saved = [t["details"]["l2_branch"]["paths"] for t in context.tickets]
    assert sum(len(paths) for paths in saved) == 131
    links = [link for g in data["graph"]["tickets"] for link in g["links"]]
    assert len({link["entity"] for link in links}) == 1 and len(links) == 10
    assert len(data["graph"]["peer_tickets"]) == 21
    assert len({i for link in links for ids in link["to"].values() for i in ids}) == 21
    assert not any("omitted" in link for link in links)
    # 변경 전은 한도를 크게 넘었고, 변경 후는 안에 든다
    assert total_chars(before_data(context)) > 4 * limit()
    assert total_chars(data) <= limit(), key_chars(data)


def over_limit_from(start: int) -> int:
    paths = start
    while total_chars(build_context(server_shape(paths)).investigate_data()) <= limit():
        paths += 1
    return paths


def test_inputs_known_to_exceed_the_limit_are_recorded() -> None:
    # 한도를 넘는 것이 알려진 입력이다. 연결 수 상한과 max_input_chars는 바꾸지 않는다(#396)
    worst = build_context(worst_shape()).investigate_data()
    assert total_chars(worst) > limit(), key_chars(worst)
    # 서버와 같은 구조에서 경로가 늘면 어느 경로 수부터 한도를 넘는가(개발 기록에 값을 적는다)
    first_over = over_limit_from(131)
    assert 131 < first_over < 500
