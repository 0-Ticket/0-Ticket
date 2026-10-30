"""C22 core checks the Schema cannot express (unnumbered queue, docs/data-contracts.md C22)."""

import pytest
from evidence_fakes import default_settings, load

from soc.l1.evidence.base import EvidenceRequestRejected
from soc.l1.evidence.checks import check_request, check_result


@pytest.fixture
def mcp():
    return default_settings().mcp


@pytest.mark.parametrize(
    "name",
    ["siem_mcp_alert_request.json", "specialist_ticket_request.json", "lookup_ticket_request.json"],
)
def test_valid_requests_pass(mcp, name):
    request = load(name)
    assert check_request(request, mcp) == request


def test_end_before_start_is_rejected(mcp):
    with pytest.raises(EvidenceRequestRejected, match="end_at"):
        check_request(load("invalid_end_before_start.json"), mcp)


def test_equal_start_and_end_are_accepted(mcp):
    request = load("siem_mcp_alert_request.json")
    request["params"]["end_at"] = request["params"]["start_at"]
    assert check_request(request, mcp) == request


def test_limit_above_max_query_limit_is_rejected(mcp):
    assert mcp.max_query_limit == 500
    with pytest.raises(EvidenceRequestRejected, match="max_query_limit"):
        check_request(load("invalid_limit_over_max.json"), mcp)


def test_limit_at_max_query_limit_is_accepted(mcp):
    request = load("invalid_limit_over_max.json")
    request["params"]["limit"] = mcp.max_query_limit
    assert check_request(request, mcp) == request


def test_incident_requester_is_rejected(mcp):
    with pytest.raises(EvidenceRequestRejected, match="incident"):
        check_request(load("invalid_incident_requester.json"), mcp)


def completed(finding_name):
    return load("specialist_ticket_request.json") | {
        "status": "completed",
        "result": {"finding": load(finding_name)},
    }


def test_finding_for_the_requesting_ticket_is_accepted():
    request = completed("specialist_finding.json")
    assert check_result(request) == request


def test_finding_for_another_ticket_is_rejected():
    with pytest.raises(EvidenceRequestRejected, match="ticket_id"):
        check_result(completed("specialist_finding_wrong_ticket.json"))


def test_rejection_message_carries_no_request_values(mcp):
    request = load("invalid_end_before_start.json")
    with pytest.raises(EvidenceRequestRejected) as caught:
        check_request(request, mcp)
    message = str(caught.value)
    assert request["params"]["entity"]["value"] not in message
    assert str(request["params"]["end_at"]) not in message
