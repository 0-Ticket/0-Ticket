"""The browser and Python share synthetic contract objects, not copied datasets."""

import json
from pathlib import Path

from soc.contracts import validate_contract

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures/frontend"
CONTRACTS = {
    "tickets": "Ticket",
    "alerts": "AlertRecord",
    "raw": "RawRecord",
    "events": "EventRecord",
    "incidents": "Incident",
    "artifacts": "IncidentArtifact",
    "cases": "Case",
    "hunts": "HuntFinding",
    "rules": "RuleProposal",
    "findings": "SpecialistFinding",
    "steps": "AgentStep",
    "reviews": "HumanReview",
    "l2_reviews": "L2Review",
    "normalize_failures": "NormalizeFailure",
}


def test_frontend_fixture_contracts():
    scenarios = json.loads((FIXTURES / "scenarios.json").read_text(encoding="utf-8"))
    assert scenarios.keys() == CONTRACTS.keys()
    for collection, name in CONTRACTS.items():
        for item in scenarios[collection]:
            validate_contract(name, item)
    responses = json.loads((FIXTURES / "api-responses.json").read_text(encoding="utf-8"))
    for page in ("empty", "first_page", "last_page"):
        for ticket in responses[page]["items"]:
            validate_contract("Ticket", ticket)


def test_frontend_fixture_references():
    data = json.loads((FIXTURES / "scenarios.json").read_text(encoding="utf-8"))
    ids = {
        key: {row[field] for row in data[key]}
        for key, field in {
            "tickets": "ticket_id",
            "alerts": "alert_id",
            "raw": "raw_id",
            "events": "event_id",
            "incidents": "incident_id",
            "cases": "case_id",
            "hunts": "hunt_id",
            "rules": "proposal_id",
        }.items()
    }
    for ticket in data["tickets"]:
        assert set(ticket["alert_ids"]) <= ids["alerts"]
    for alert in data["alerts"] + data["events"]:
        assert set(alert["raw_ids"]) <= ids["raw"]
    for incident in data["incidents"]:
        for member in incident["members"]:
            key, field = (
                ("tickets", "ticket_id")
                if member["member_type"] == "ticket"
                else ("hunts", "hunt_id")
            )
            assert member[field] in ids[key]
    for case in data["cases"]:
        assert case["incident_id"] in ids["incidents"]
    for rule in data["rules"]:
        assert rule["hunt_id"] in ids["hunts"] or rule["case_id"] in ids["cases"]
    evidence_ids = {
        "alert": ids["alerts"],
        "event": ids["events"],
        "raw": ids["raw"],
        "ticket": ids["tickets"],
    }

    def check_evidence(value):
        if isinstance(value, dict):
            if {"ref_type", "ref_id", "note"} <= value.keys():
                assert value["ref_id"] in evidence_ids[value["ref_type"]]
            for nested in value.values():
                check_evidence(nested)
        elif isinstance(value, list):
            for nested in value:
                check_evidence(nested)

    check_evidence(data)


def test_f1_fixture_sort_boundaries():
    data = json.loads((FIXTURES / "scenarios.json").read_text(encoding="utf-8"))
    ordered = sorted(
        data["tickets"],
        key=lambda ticket: (-ticket["priority"], ticket["created_at"], ticket["ticket_id"]),
    )
    assert [ticket["ticket_id"] for ticket in ordered] == [
        "tk_sample",
        "tk_cloud",
        "tk_custom",
        "tk_tie_a",
        "tk_tie_z",
        "tk_later",
    ]
    assert len({ticket["status"] for ticket in ordered}) > 1
    assert any(ticket["verdict"] is None for ticket in ordered)
    assert any(len(ticket["alert_ids"]) > 1 for ticket in ordered)


def test_ticket_detail_fixture_contracts_and_references():
    detail = json.loads((FIXTURES / "ticket-detail.json").read_text(encoding="utf-8"))
    assert set(detail) == {
        "ticket",
        "alerts",
        "findings",
        "decisions",
        "evidence_requests",
        "steps",
        "reviews",
        "incident_ids",
    }
    validate_contract("Ticket", detail["ticket"])
    for key, name in {
        "alerts": "AlertRecord",
        "findings": "SpecialistFinding",
        "decisions": "L1DecisionRecord",
        "evidence_requests": "EvidenceRequest",
        "steps": "AgentStep",
        "reviews": "HumanReview",
    }.items():
        for item in detail[key]:
            validate_contract(name, item)
    data = json.loads((FIXTURES / "scenarios.json").read_text(encoding="utf-8"))
    ids = {
        kind: {row[field] for row in data[key]}
        for kind, key, field in [
            ("alert", "alerts", "alert_id"),
            ("event", "events", "event_id"),
            ("raw", "raw", "raw_id"),
        ]
    }
    for evidence in detail["ticket"]["verdict"]["evidence"]:
        if evidence["ref_type"] in ids:
            assert evidence["ref_id"] in ids[evidence["ref_type"]]
    assert set(detail["ticket"]["alert_ids"]) == {a["alert_id"] for a in detail["alerts"]}
    assert set(detail["incident_ids"]) <= {i["incident_id"] for i in data["incidents"]}
    assert all(s["subject_id"] == detail["ticket"]["ticket_id"] for s in detail["steps"])


def test_incident_detail_fixture_contracts_and_references():
    extra = json.loads((FIXTURES / "incident-detail.json").read_text(encoding="utf-8"))
    assert set(extra) <= CONTRACTS.keys()
    for collection, items in extra.items():
        for item in items:
            validate_contract(CONTRACTS[collection], item)
    data = json.loads((FIXTURES / "scenarios.json").read_text(encoding="utf-8"))
    ids = {
        kind: {row[field] for row in data[key] + extra.get(key, [])}
        for kind, key, field in [
            ("alert", "alerts", "alert_id"),
            ("event", "events", "event_id"),
            ("raw", "raw", "raw_id"),
            ("ticket", "tickets", "ticket_id"),
            ("hunt", "hunts", "hunt_id"),
            ("incident", "incidents", "incident_id"),
        ]
    }
    for incident in extra["incidents"]:
        for member in incident["members"]:
            assert member[f"{member['member_type']}_id"] in ids[member["member_type"]]
    for key in ("artifacts", "steps", "l2_reviews"):
        for item in extra[key]:
            assert item.get("incident_id", item.get("subject_id")) in ids["incident"]
    for hunt in extra["hunts"]:
        assert hunt["incident_id"] in ids["incident"]
    for artifact in extra["artifacts"]:
        times = [entry["time"] for entry in artifact["timeline"]]
        assert times == sorted(times)
        for entry in artifact["timeline"]:
            for evidence in entry["evidence"]:
                # Plugin-registered types have no documented lookup; keep them as text.
                if evidence["ref_type"] in ids:
                    assert evidence["ref_id"] in ids[evidence["ref_type"]]
    assert any(
        e["ref_type"] not in ids
        for a in extra["artifacts"]
        for t in a["timeline"]
        for e in t["evidence"]
    )


def test_incident_review_fixtures_follow_box36_flow():
    # Synthetic mock states must tell a consistent box 36 story (#21); the screen never
    # derives them, so this only checks the hand-written fixtures.
    data = json.loads((FIXTURES / "scenarios.json").read_text(encoding="utf-8"))
    extra = json.loads((FIXTURES / "incident-detail.json").read_text(encoding="utf-8"))
    case_extra = json.loads((FIXTURES / "case-detail.json").read_text(encoding="utf-8"))
    incidents = data["incidents"] + extra["incidents"] + case_extra["incidents"]
    reviews = data["l2_reviews"] + extra["l2_reviews"] + case_extra["l2_reviews"]
    artifacts = {
        a["incident_id"] for a in data["artifacts"] + extra["artifacts"] + case_extra["artifacts"]
    }
    cases = {c["incident_id"] for c in data["cases"] + case_extra["cases"]}
    scenario = {}
    for incident in incidents:
        incident_id, state = incident["incident_id"], incident["review_state"]
        mine = sorted(
            (r for r in reviews if r["incident_id"] == incident_id), key=lambda r: r["round"]
        )
        rounds = [r["round"] for r in mine]
        rejects = sum(r["decision"] == "reject" for r in mine)
        assert rounds == list(range(1, len(rounds) + 1)), incident_id
        # Only rejections continue the loop; an approval is always the last review.
        assert all(r["decision"] == "reject" for r in mine[:-1]), incident_id
        if mine:
            # L2 review happens after investigation starts, never on a fresh Incident.
            assert incident["status"] != "open", incident_id
        if incident_id in cases:
            assert state == "approved", incident_id
        if state == "awaiting_review":
            assert incident["review_round"] == len(rounds) + 1, incident_id
            assert rejects < 2 and incident_id in artifacts, incident_id
            assert incident["status"] == "investigating", incident_id
        elif state == "analyzing":
            assert rejects < 2 and (not mine or mine[-1]["decision"] == "reject"), incident_id
            assert incident["status"] == "investigating", incident_id
        elif state == "approved":
            assert mine and mine[-1]["decision"] == "approve", incident_id
        else:
            assert state == "human_handling"
            assert rejects == 2 and mine[-1]["decision"] == "reject", incident_id
        scenario[incident_id] = (state, incident["review_round"], rejects)
    assert scenario["in_web_campaign"] == ("awaiting_review", 1, 0)
    assert scenario["in_reanalysis"] == ("analyzing", None, 1)
    assert scenario["in_second_round"] == ("awaiting_review", 2, 1)
    assert scenario["in_manual"] == ("human_handling", None, 2)
    assert scenario["in_benign"] == ("human_handling", None, 2)
    assert scenario["in_sample"] == ("approved", None, 0)
    assert scenario["in_escalated"] == ("approved", None, 0)
    assert scenario["in_contained"] == ("approved", None, 0)


def test_case_detail_fixture_contracts_and_references():
    extra = json.loads((FIXTURES / "case-detail.json").read_text(encoding="utf-8"))
    assert set(extra) <= CONTRACTS.keys()
    for collection, items in extra.items():
        for item in items:
            validate_contract(CONTRACTS[collection], item)
    data = json.loads((FIXTURES / "scenarios.json").read_text(encoding="utf-8"))
    incident_extra = json.loads((FIXTURES / "incident-detail.json").read_text(encoding="utf-8"))
    incidents = data["incidents"] + incident_extra["incidents"] + extra["incidents"]
    ids = {
        kind: {row[field] for row in data[key] + incident_extra.get(key, [])}
        for kind, key, field in [
            ("alert", "alerts", "alert_id"),
            ("event", "events", "event_id"),
            ("raw", "raw", "raw_id"),
            ("ticket", "tickets", "ticket_id"),
        ]
    }
    incident_ids = {i["incident_id"] for i in incidents}
    cases = data["cases"] + extra["cases"]
    # One Case per Incident; the mock links an Incident to its Case by incident_id.
    assert len({c["incident_id"] for c in cases}) == len(cases)
    assert len({c["case_id"] for c in cases}) == len(cases)
    for incident in extra["incidents"]:
        for member in incident["members"]:
            assert member["ticket_id"] in ids["ticket"]
    for case in cases:
        assert case["incident_id"] in incident_ids
        # closed_at is set exactly when the Case is closed; lessons are written on close.
        assert (case["status"] == "closed") == (case["closed_at"] is not None), case["case_id"]
        if case["status"] != "closed":
            assert case["lessons"] is None, case["case_id"]
    statuses = {c["status"] for c in extra["cases"]}
    assert {"responding", "closed"} <= statuses
    tasks = [t for c in extra["cases"] for t in c["tasks"]]
    assert {t["status"] for t in tasks} == {"todo", "doing", "done"}
    assert any(t["due_at"] is None for t in tasks)
    existing_artifacts = {a["incident_id"] for a in data["artifacts"] + incident_extra["artifacts"]}
    for artifact in extra["artifacts"]:
        assert artifact["incident_id"] in {c["incident_id"] for c in extra["cases"]}
        assert artifact["incident_id"] not in existing_artifacts
        times = [entry["time"] for entry in artifact["timeline"]]
        assert times == sorted(times)
        for entry in artifact["timeline"]:
            for evidence in entry["evidence"]:
                if evidence["ref_type"] in ids:
                    assert evidence["ref_id"] in ids[evidence["ref_type"]]
    case_ids = {c["case_id"] for c in cases}
    for rule in extra["rules"]:
        assert rule["case_id"] in case_ids


def test_hunt_rule_fixture_contracts_and_references():
    extra = json.loads((FIXTURES / "hunt-rule-detail.json").read_text(encoding="utf-8"))
    assert set(extra) <= CONTRACTS.keys()
    for collection, items in extra.items():
        for item in items:
            validate_contract(CONTRACTS[collection], item)
    data = json.loads((FIXTURES / "scenarios.json").read_text(encoding="utf-8"))
    incident_extra = json.loads((FIXTURES / "incident-detail.json").read_text(encoding="utf-8"))
    case_extra = json.loads((FIXTURES / "case-detail.json").read_text(encoding="utf-8"))
    hunts = data["hunts"] + incident_extra["hunts"] + extra["hunts"]
    hunt_ids = [h["hunt_id"] for h in hunts]
    assert len(set(hunt_ids)) == len(hunt_ids)
    incidents = data["incidents"] + incident_extra["incidents"] + case_extra["incidents"]
    members = {
        (i["incident_id"], m["hunt_id"]) for i in incidents for m in i["members"] if m["hunt_id"]
    }
    events = {e["event_id"] for e in data["events"]}
    for hunt in extra["hunts"]:
        # A hunt links to an Incident only when Correlation grouped it (member_type hunt).
        if hunt["incident_id"] is not None:
            assert (hunt["incident_id"], hunt["hunt_id"]) in members
        if not hunt["is_anomaly"]:
            assert hunt["incident_id"] is None
        for evidence in hunt["evidence"]:
            if evidence["ref_type"] == "event":
                assert evidence["ref_id"] in events
    # Unknown registered ref_type is kept to check the screen shows it as the original string.
    assert any(
        e["ref_type"] not in {"alert", "event", "raw", "ticket"}
        for h in extra["hunts"]
        for e in h["evidence"]
    )
    steps = extra["steps"]
    assert {s["subject_type"] for s in steps} == {"hunt"}
    assert {s["subject_id"] for s in steps} <= set(hunt_ids)
    for step in steps:
        hunt = next(h for h in hunts if h["hunt_id"] == step["subject_id"])
        assert step["created_at"] <= hunt["created_at"]
    keys = [(s["subject_id"], s["step"]) for s in steps]
    assert len(set(keys)) == len(keys)
    rules = data["rules"] + case_extra["rules"] + extra["rules"]
    proposal_ids = [r["proposal_id"] for r in rules]
    assert len(set(proposal_ids)) == len(proposal_ids)
    hunt_by_id = {h["hunt_id"]: h for h in hunts}
    case_by_id = {c["case_id"]: c for c in data["cases"] + case_extra["cases"]}
    for rule in extra["rules"]:
        assert rule["hunt_id"] is None or rule["hunt_id"] in hunt_by_id
        assert rule["case_id"] is None or rule["case_id"] in case_by_id
        # A proposal comes from a hunt marked as a rule candidate, after that hunt or Case.
        if rule["hunt_id"]:
            basis = hunt_by_id[rule["hunt_id"]]
            assert basis["rule_candidate"], rule["proposal_id"]
            assert basis["created_at"] < rule["created_at"]
        if rule["case_id"]:
            assert case_by_id[rule["case_id"]]["created_at"] < rule["created_at"]
        if rule["backtest"]:
            window = rule["backtest"]
            assert window["window_start_at"] < window["window_end_at"] <= rule["created_at"]
        # The mock records a reviewer only when a draft is reviewed.
        assert (rule["status"] == "draft") == (rule["reviewer"] is None), rule["proposal_id"]
    assert {r["status"] for r in extra["rules"]} == {"draft", "approved", "rejected", "deployed"}
    assert any(r["backtest"] is None for r in extra["rules"])
    assert any(not r["syntax_ok"] for r in extra["rules"])
    assert any(r["hunt_id"] is None and r["case_id"] for r in extra["rules"])


L1_CONTRACTS = {
    "alerts": "AlertRecord",
    "tickets": "Ticket",
    "branches": "BranchResult",
    "decisions": "L1DecisionRecord",
    "evidence_requests": "EvidenceRequest",
    "steps": "AgentStep",
}


def test_l1_result_fixture_contracts_and_references():
    extra = json.loads((FIXTURES / "l1-results.json").read_text(encoding="utf-8"))
    assert extra.keys() == L1_CONTRACTS.keys()
    for collection, name in L1_CONTRACTS.items():
        for item in extra[collection]:
            validate_contract(name, item)
    data = json.loads((FIXTURES / "scenarios.json").read_text(encoding="utf-8"))
    alert_ids = {row["alert_id"] for row in data["alerts"] + extra["alerts"]}
    ticket_ids = {row["ticket_id"] for row in data["tickets"] + extra["tickets"]}
    raw_ids = {row["raw_id"] for row in data["raw"]}
    subjects = {"alert": alert_ids, "ticket": ticket_ids}
    for ticket in extra["tickets"]:
        assert set(ticket["alert_ids"]) <= alert_ids
    for alert in extra["alerts"]:
        assert set(alert["raw_ids"]) <= raw_ids
    for item in extra["branches"] + extra["decisions"] + extra["steps"]:
        assert item["subject_id"] in subjects[item["subject_type"]]
    for request in extra["evidence_requests"]:
        assert request["requester_id"] in subjects[request["requester_type"]]
    for evidence in (
        ticket["verdict"]["evidence"] for ticket in extra["tickets"] if ticket["verdict"]
    ):
        for item in evidence:
            assert item["ref_id"] in {"alert": alert_ids, "raw": raw_ids}[item["ref_type"]]


def test_l1_result_fixture_covers_every_decision_and_hold_reason():
    # F1 and F2 show promotions, holds and verdicts apart; the sample must carry one of each.
    extra = json.loads((FIXTURES / "l1-results.json").read_text(encoding="utf-8"))
    decisions = extra["decisions"]
    assert {d["decision"] for d in decisions} == {
        "l1_escalated",
        "held",
        "closed_fp",
        "l2_escalated",
    }
    assert {d["reason"] for d in decisions if d["decision"] == "held"} == {
        "below_threshold",
        "llm_failure",
        "evidence_request_failure",
    }
    assert {d["reason"] for d in decisions if d["decision"] != "held"} == {None}
    assert any(d["confidence"] is None for d in decisions)
    # A failed request is the "증거 수집 실패" the screen shows (D-034, K62).
    failed = [r for r in extra["evidence_requests"] if r["status"] == "failed"]
    assert {r["requester_type"] for r in failed} == {"alert", "ticket"}
    assert all(r["retry_count"] > 0 and r["failure_reason"] for r in failed)
    assert {r["request_type"] for r in extra["evidence_requests"]} == {
        "lookup",
        "siem_mcp",
        "specialist_agent",
    }
    # v2 Ticket statuses and origins, and an alert-level Agent Log step for the merged F2 log.
    assert {t["status"] for t in extra["tickets"]} == {"on_hold", "closed_fp", "l2_escalated"}
    assert {t["origin"] for t in extra["tickets"]} == {"l1_escalated", "scenario"}
    assert any(s["subject_type"] == "alert" for s in extra["steps"])
    assert any(s["subject_type"] == "ticket" for s in extra["steps"])
