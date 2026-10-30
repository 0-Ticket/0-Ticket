"""Rules every evidence queue backend must follow (unnumbered, K59).

A backend test subclasses ``EvidenceQueueContract`` and provides ``make_queue``,
a fixture returning a function that opens a queue. The PostgreSQL test calls it
twice to get two connections onto the same table.
"""

import pytest
from evidence_fakes import AGENT, load

from soc.contracts import ContractValidationError
from soc.l1.evidence.base import DuplicateRequestError, RequestStateError

NOW = 1791849700000


def numbered(name: str, number: int) -> dict:
    return load(name) | {"request_id": f"rq_contract_{number}"}


class EvidenceQueueContract:
    @pytest.fixture
    def make_queue(self):
        raise NotImplementedError

    def test_enqueued_request_is_stored_as_c22(self, make_queue):
        queue = make_queue()
        request = load("siem_mcp_alert_request.json")

        assert queue.enqueue(request, agent=AGENT) == request
        assert queue.get(request["request_id"]) == request
        assert queue.get("rq_missing") is None

    def test_same_request_id_cannot_be_queued_twice(self, make_queue):
        queue = make_queue()
        queue.enqueue(load("siem_mcp_alert_request.json"), agent=AGENT)

        with pytest.raises(DuplicateRequestError):
            queue.enqueue(load("siem_mcp_alert_request.json"), agent=AGENT)

    def test_request_that_breaks_c22_is_not_stored(self, make_queue):
        queue = make_queue()
        broken = load("siem_mcp_alert_request.json") | {"request_type": "specialist_agent"}

        with pytest.raises(ContractValidationError):
            queue.enqueue(broken, agent=AGENT)
        assert queue.get(broken["request_id"]) is None

    def test_requests_are_claimed_in_arrival_order(self, make_queue):
        queue = make_queue()
        # IDs sort the other way round, so only arrival order can pass this.
        for number in (3, 1, 2):
            queue.enqueue(numbered("lookup_ticket_request.json", number), agent=AGENT)

        claimed = [queue.claim_next(now_ms=NOW).request["request_id"] for _ in range(3)]

        assert claimed == ["rq_contract_3", "rq_contract_1", "rq_contract_2"]
        assert queue.claim_next(now_ms=NOW) is None

    def test_claim_marks_the_request_in_progress_and_keeps_the_agent(self, make_queue):
        queue = make_queue()
        queue.enqueue(load("siem_mcp_alert_request.json"), agent="l1_entity")

        claimed = queue.claim_next(now_ms=NOW)

        assert claimed.agent == "l1_entity"
        assert claimed.request["status"] == "in_progress"
        assert claimed.request["updated_at"] == NOW
        assert queue.get(claimed.request["request_id"]) == claimed.request

    def test_claimed_request_is_not_claimed_twice(self, make_queue):
        first, second = make_queue(), make_queue()
        first.enqueue(load("siem_mcp_alert_request.json"), agent=AGENT)

        assert first.claim_next(now_ms=NOW) is not None
        assert second.claim_next(now_ms=NOW) is None
        assert first.claim_next(now_ms=NOW) is None

    def test_completed_result_is_readable_by_requester(self, make_queue):
        queue = make_queue()
        queue.enqueue(load("specialist_ticket_request.json"), agent=AGENT)
        queue.enqueue(load("lookup_ticket_request.json"), agent=AGENT)
        queue.enqueue(load("siem_mcp_alert_request.json"), agent=AGENT)
        claimed = queue.claim_next(now_ms=NOW).request
        completed = claimed | {
            "status": "completed",
            "result": {"finding": load("specialist_finding.json")},
            "updated_at": NOW + 1,
        }

        queue.update(completed, expected_status="in_progress")

        found = queue.list_by_requester("ticket", "tk_ticket_sample")
        assert [item["request_id"] for item in found] == [
            "rq_specialist_sample",
            "rq_lookup_sample",
        ]
        assert found[0] == completed
        assert queue.list_by_requester("alert", "al_sample")[0]["status"] == "pending"

    def test_update_from_an_unexpected_status_is_rejected(self, make_queue):
        queue = make_queue()
        request = queue.enqueue(load("siem_mcp_alert_request.json"), agent=AGENT)
        failed = request | {"status": "failed", "failure_reason": "HandlerError"}

        with pytest.raises(RequestStateError):
            queue.update(failed, expected_status="in_progress")
        assert queue.get(request["request_id"]) == request

    def test_release_puts_in_progress_requests_back_in_line(self, make_queue):
        queue = make_queue()
        for number in (1, 2, 3):
            queue.enqueue(numbered("lookup_ticket_request.json", number), agent=AGENT)
        queue.claim_next(now_ms=NOW)
        queue.claim_next(now_ms=NOW)

        assert queue.release_in_progress(now_ms=NOW + 5) == 2

        released = queue.get("rq_contract_1")
        assert released["status"] == "pending"
        assert released["updated_at"] == NOW + 5
        claimed = [queue.claim_next(now_ms=NOW).request["request_id"] for _ in range(3)]
        assert claimed == ["rq_contract_1", "rq_contract_2", "rq_contract_3"]
