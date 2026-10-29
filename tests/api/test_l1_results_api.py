"""The read-only L1 result API (box 27, K60, docs/api-contracts.md).

Every test drives the FastAPI app over fake stores, so the shapes checked here
are the ones docs/api-contracts.md promises the screen and the mock (D-022).
"""

import json
from contextlib import contextmanager
from pathlib import Path

import pytest
from agent_log_fakes import FakeAgentLogStore
from evidence_fakes import FakeEvidenceQueue
from fake_branch_store import FakeBranchStore
from fake_l1_decision_store import FakeL1DecisionStore
from fake_ticket_store import FakeTicketStore
from fastapi.testclient import TestClient

from soc.api import ApiReaders, create_app
from soc.contracts import validate_contract
from soc.l1.agent_log import AgentLogService

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "api" / "l1_results.json"


class FakeAlertReader:
    """The one Alert operation box 27 uses: read a stored C5 by its ID.

    The real store (``readonly_records``) has its own contract tests; seeding it
    needs the C2 source rows box 3 hashes, which this box never reads.
    """

    def __init__(self, alerts=()):
        self.alerts = {alert.alert_id: alert for alert in alerts}
        self.closed = False

    def get_alert_record(self, alert_id):
        return self.alerts.get(alert_id)

    def close(self):
        self.closed = True


class FakeReaderPool:
    """Stands in for the connection pool: every request gets the same fake stores,
    the way the real pool gives each request stores on a borrowed connection (#104)."""

    def __init__(self, request_readers):
        self._readers = request_readers
        self.opened = 0
        self.closed = 0

    def open(self):
        self.opened += 1

    def close(self):
        self.closed += 1

    @contextmanager
    def readers(self):
        yield self._readers


def load_fixture():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def decision_record(decision_id, subject_id, created_at, subject_type="alert"):
    return validate_contract(
        "L1DecisionRecord",
        {
            "decision_id": decision_id,
            "subject_type": subject_type,
            "subject_id": subject_id,
            "decision": "held",
            "confidence": None,
            "reason": "below_threshold",
            "created_at": created_at,
        },
    )


@pytest.fixture
def data():
    return load_fixture()


@pytest.fixture
def readers(data, tmp_path):
    """Readers over fake stores, filled with the fixture scenario."""
    tickets = FakeTicketStore()
    records = FakeAlertReader(validate_contract("AlertRecord", alert) for alert in data["alerts"])
    decisions, branches, queue = FakeL1DecisionStore(), FakeBranchStore(), FakeEvidenceQueue()
    agent_log_store = FakeAgentLogStore()

    for ticket in data["tickets"]:
        tickets.create(ticket)
    for item in data["decisions"]:
        decisions.save(validate_contract("L1DecisionRecord", item))
    for item in data["branches"]:
        branches.save(validate_contract("BranchResult", item))
    for request in data["evidence_requests"]:
        queue.enqueue(request, agent="l1")
    service = AgentLogService(agent_log_store, tmp_path, ticket_store_factory=lambda: tickets)
    for step in data["steps"]:
        service.record(step)

    return ApiReaders(
        tickets=tickets,
        records=records,
        decisions=decisions,
        branches=branches,
        evidence_queue=queue,
        agent_log=service,
    )


@pytest.fixture
def reader_pool(readers):
    return FakeReaderPool(readers)


@pytest.fixture
def client(reader_pool):
    with TestClient(create_app(reader_pool)) as client:
        yield client


def get(client, path, **params):
    response = client.get(path, params=params)
    return response.status_code, response.json()


def test_the_api_has_no_write_routes(reader_pool):
    """Box 27 is read-only: no path may accept a write method (K60)."""
    methods = set()
    for route in create_app(reader_pool).routes:
        methods |= set(getattr(route, "methods", ()))
    assert methods <= {"GET", "HEAD"}


def test_ticket_list_returns_contract_tickets_in_api_order(client, data):
    status, body = get(client, "/api/tickets")
    assert status == 200
    assert [ticket["ticket_id"] for ticket in body["items"]] == [
        "tk_api_escalated",
        "tk_api_scenario_held",
    ]
    assert body["next_cursor"] is None
    assert body["items"][0] == data["tickets"][0]


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"status": "on_hold"}, ["tk_api_scenario_held"]),
        ({"origin": "l1_escalated"}, ["tk_api_escalated"]),
        ({"handling_type": "scan"}, ["tk_api_scenario_held"]),
        ({"min_priority": "10"}, ["tk_api_escalated"]),
        ({"origin": "scenario", "min_priority": "1"}, ["tk_api_scenario_held"]),
        ({"status": "closed_fp"}, []),
    ],
)
def test_ticket_list_filters(client, params, expected):
    status, body = get(client, "/api/tickets", **params)
    assert status == 200
    assert [ticket["ticket_id"] for ticket in body["items"]] == expected


def test_ticket_list_pages_with_the_cursor(client):
    status, first = get(client, "/api/tickets", limit="1")
    assert status == 200
    assert [t["ticket_id"] for t in first["items"]] == ["tk_api_escalated"]
    assert first["next_cursor"] is not None

    status, second = get(client, "/api/tickets", limit="1", cursor=first["next_cursor"])
    assert status == 200
    assert [t["ticket_id"] for t in second["items"]] == ["tk_api_scenario_held"]
    assert second["next_cursor"] is None


def test_ticket_detail_has_decisions_evidence_requests_and_findings(client, data):
    status, body = get(client, "/api/tickets/tk_api_escalated")
    assert status == 200
    assert body["ticket"] == data["tickets"][0]
    # Only the completed specialist_agent request contributes a C14.
    assert body["findings"] == [data["evidence_requests"][0]["result"]["finding"]]
    assert [item["decision_id"] for item in body["decisions"]] == ["ld_api_ticket_escalated"]
    assert [item["request_id"] for item in body["evidence_requests"]] == [
        "rq_api_specialist_done",
        "rq_api_lookup_done",
        "rq_api_siem_failed",
        "rq_api_lookup_pending",
    ]
    # The failed request is how box 27 shows evidence collection failure (K62).
    failed = next(item for item in body["evidence_requests"] if item["status"] == "failed")
    assert failed["failure_reason"] == "siem_mcp timed out after 3 retries"


def test_ticket_detail_has_no_reviews_or_incidents_in_v2(client):
    _, body = get(client, "/api/tickets/tk_api_escalated")
    assert body["reviews"] == [] and body["incident_ids"] == []


def test_ticket_detail_merges_ticket_and_alert_steps_in_time_order(client):
    """The ticket's own steps and its alerts' steps, oldest first (#44)."""
    _, body = get(client, "/api/tickets/tk_api_escalated")
    assert [(step["subject_id"], step["created_at"]) for step in body["steps"]] == [
        ("al_api_sqli", 1791849600800),
        ("tk_api_escalated", 1791849605000),
    ]


def test_steps_carry_c8_fields_only(client, data):
    """Local artifact paths and hashes are not part of the API contract."""
    _, body = get(client, "/api/tickets/tk_api_escalated")
    for step in body["steps"]:
        assert set(step) == set(data["steps"][0])
        validate_contract("AgentStep", step)


def test_ticket_detail_skips_an_alert_id_missing_from_the_store(client):
    _, body = get(client, "/api/tickets/tk_api_escalated")
    assert [alert["alert_id"] for alert in body["alerts"]] == ["al_api_sqli"]
    # The ID stays in the Ticket so the screen can still show it.
    assert body["ticket"]["alert_ids"] == ["al_api_sqli", "al_api_gone"]


def test_alert_detail_returns_the_contract_record(client, data):
    status, body = get(client, "/api/alerts/al_api_sqli")
    assert status == 200
    assert body == data["alerts"][0]


def test_held_alert_l1_detail_returns_c5_c21_c23_c22_and_c8(client, data):
    status, body = get(client, "/api/alerts/al_api_held/l1")
    assert status == 200
    assert body["alert"] == data["alerts"][1]
    assert body["branch"]["branch_id"] == "br_api_held"
    # Newest decision first: the whole history of the alert, not only the latest.
    assert [item["decision_id"] for item in body["decisions"]] == [
        "ld_api_alert_held_llm",
        "ld_api_alert_held_threshold",
    ]
    assert [item["request_id"] for item in body["evidence_requests"]] == ["rq_api_alert_lookup"]
    assert [step["subject_id"] for step in body["steps"]] == ["al_api_held"]


def test_an_alert_without_a_branch_or_decision_is_not_an_error(client):
    status, body = get(client, "/api/alerts/al_api_plain/l1")
    assert status == 200
    assert body["branch"] is None
    assert body["decisions"] == [] and body["evidence_requests"] == [] and body["steps"] == []


def test_detail_reads_every_decision_page(client, readers):
    """A subject with more decisions than one page still returns all of them."""
    for index in range(120):
        readers.decisions.save(decision_record(f"ld_many_{index:03d}", "al_api_plain", 1 + index))

    _, body = get(client, "/api/alerts/al_api_plain/l1")
    assert len(body["decisions"]) == 120
    assert body["decisions"][0]["decision_id"] == "ld_many_119"


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({}, 5),
        ({"subject_type": "ticket"}, 2),
        ({"decision": "held"}, 3),
        ({"reason": "llm_failure"}, 1),
        ({"subject_type": "alert", "decision": "l1_escalated"}, 1),
        ({"subject_type": "ticket", "reason": "below_threshold"}, 0),
    ],
)
def test_l1_decision_list_filters(client, params, expected):
    status, body = get(client, "/api/l1/decisions", **params)
    assert status == 200
    assert len(body["items"]) == expected


def test_l1_decision_list_is_newest_first_and_pages(client):
    _, first = get(client, "/api/l1/decisions", limit="2")
    assert [item["decision_id"] for item in first["items"]] == [
        "ld_api_ticket_held",
        "ld_api_alert_held_llm",
    ]
    _, second = get(client, "/api/l1/decisions", limit="2", cursor=first["next_cursor"])
    assert [item["decision_id"] for item in second["items"]] == [
        "ld_api_alert_held_threshold",
        "ld_api_ticket_escalated",
    ]


@pytest.mark.parametrize(
    "path",
    [
        "/api/tickets/tk_missing",
        "/api/alerts/al_missing",
        "/api/alerts/al_missing/l1",
    ],
)
def test_unknown_ids_return_not_found(client, path):
    status, body = get(client, path)
    assert status == 404
    assert body["error"]["code"] == "not_found"


@pytest.mark.parametrize(
    ("path", "params"),
    [
        ("/api/tickets", {"status": "done"}),
        ("/api/tickets", {"origin": "manual"}),
        ("/api/tickets", {"handling_type": ""}),
        ("/api/tickets", {"min_priority": "-1"}),
        ("/api/tickets", {"limit": "0"}),
        ("/api/tickets", {"limit": "201"}),
        ("/api/tickets", {"cursor": "%%%"}),
        ("/api/l1/decisions", {"subject_type": "incident"}),
        ("/api/l1/decisions", {"decision": "closed_benign"}),
        ("/api/l1/decisions", {"reason": "timeout"}),
        ("/api/l1/decisions", {"cursor": "WyJ4Il0="}),
    ],
)
def test_bad_filters_cursors_and_limits_are_invalid_input(client, path, params):
    status, body = get(client, path, **params)
    assert status == 400
    assert body["error"]["code"] == "invalid_input"
    assert body["error"]["message"]


@pytest.mark.parametrize("value", ["abc", "1.5", ""])
def test_a_limit_that_is_not_an_integer_is_invalid_input(client, value):
    """Not the framework's own 422 shape: the error contract has one shape."""
    status, body = get(client, "/api/tickets", limit=value)
    assert status == 400
    assert body["error"]["code"] == "invalid_input"


def test_an_unexpected_error_is_internal_without_detail(readers):
    class BrokenTickets:
        def get(self, ticket_id):
            raise RuntimeError("psycopg: relation tickets does not exist at 203.0.113.9")

        def close(self):
            pass

    readers.tickets = BrokenTickets()
    app = create_app(FakeReaderPool(readers))
    with TestClient(app, raise_server_exceptions=False) as client:
        status, body = get(client, "/api/tickets/tk_api_escalated")
    assert status == 500
    assert body == {"error": {"code": "internal", "message": "internal error"}}


def test_the_pool_is_opened_and_closed_with_the_service(reader_pool):
    """The stores of a request end with the request; what the service owns is the
    pool, so it fills it on start and closes it on shutdown (#104)."""
    with TestClient(create_app(reader_pool)) as client:
        get(client, "/api/tickets")
        assert (reader_pool.opened, reader_pool.closed) == (1, 0)
    assert (reader_pool.opened, reader_pool.closed) == (1, 1)


# 지표는 집계를 쌓는 저장소가 아직 없다(C9·C15·Incident 묶음 항목). 경로는 그 사실을
# available=false로 말하고, 없다는 것을 오류로 돌려주지 않는다(#103).
def test_metrics_returns_an_empty_state_without_an_error(client):
    status, body = get(client, "/api/metrics", **{"from": 0, "to": 1})
    assert status == 200
    assert body["available"] is False
    assert set(body) == {"from", "to", "available"}


def test_metrics_window_echoes_the_requested_range(client):
    status, body = get(client, "/api/metrics", **{"from": 1791849600000, "to": 1791853200000})
    assert status == 200
    assert (body["from"], body["to"]) == (1791849600000, 1791853200000)


@pytest.mark.parametrize(
    "window",
    [
        {"from": "yesterday", "to": 1},
        {"from": 0, "to": "now"},
        {"from": 2, "to": 1},
    ],
)
def test_metrics_rejects_a_bad_window(client, window):
    status, body = get(client, "/api/metrics", **window)
    assert status == 400
    assert body["error"]["code"] == "invalid_input"
