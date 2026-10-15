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
    scenarios = json.loads((FIXTURES / "scenarios.json").read_text())
    assert scenarios.keys() == CONTRACTS.keys()
    for collection, name in CONTRACTS.items():
        for item in scenarios[collection]:
            validate_contract(name, item)
    responses = json.loads((FIXTURES / "api-responses.json").read_text())
    for page in ("empty", "first_page", "last_page"):
        for ticket in responses[page]["items"]:
            validate_contract("Ticket", ticket)


def test_frontend_fixture_references():
    data = json.loads((FIXTURES / "scenarios.json").read_text())
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
    data = json.loads((FIXTURES / "scenarios.json").read_text())
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
    detail = json.loads((FIXTURES / "ticket-detail.json").read_text())
    assert set(detail) == {"ticket", "alerts", "findings", "steps", "reviews", "incident_ids"}
    validate_contract("Ticket", detail["ticket"])
    for key, name in {
        "alerts": "AlertRecord",
        "findings": "SpecialistFinding",
        "steps": "AgentStep",
        "reviews": "HumanReview",
    }.items():
        for item in detail[key]:
            validate_contract(name, item)
    data = json.loads((FIXTURES / "scenarios.json").read_text())
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
