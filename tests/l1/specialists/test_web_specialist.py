"""Web specialist Agent: one evidence request to a checked C14 (box 14, K16, K59).

No model is called: the provider is a fake that answers with a prepared string
(docs/llm-policy.md 7). The flow is fixed by code (D-008) — read the Ticket, read
its alerts and the source's HTTP flow through the Web allowlist, then ask once.
"""

import json

import pytest
from evidence_fakes import AGENT, FakeEvidenceQueue, default_settings
from fake_records import FakeReadOnlyRecords, fixture_alerts
from llm_input_fakes import web_flow_events
from specialist_fakes import ALLOWED_TOOLS, FakeAgentLog, build_context, load, response

from soc.l1.evidence.handlers import default_handlers
from soc.l1.evidence.service import EvidenceQueueService
from soc.l1.specialists import SPECIALISTS, open_specialist
from soc.l1.specialists.web import INPUT_TOO_LARGE, WEB_AGENT, web_specialist
from soc.l1.tickets import TicketNotFoundError
from soc.plugins import PluginRegistry

TICKET = load("ticket_web.json")
REQUEST = load("specialist_request.json")
QUESTION = REQUEST["params"]["question"]
VALID = "valid_specialist_finding.json"
MALFORMED = "malformed_specialist_finding.json"
UNKNOWN_EVIDENCE = "specialist_finding_unknown_evidence.json"
NOW = 1770003600000


def analyze(tmp_path, *names, request=REQUEST, **changes):
    """Run the Web specialist over ``request`` with the given prepared answers."""
    context = build_context(tmp_path, *(response(name) for name in names), **changes)
    return web_specialist(context)(request), context


def test_finding_answers_the_question_with_stored_evidence(tmp_path):
    finding, context = analyze(tmp_path, VALID, tickets=(TICKET,))

    assert finding["succeeded"] == "unknown"
    assert finding["attack_type"] == "sqli"
    assert finding["needs_human"] is False
    assert [item["ref_id"] for item in finding["evidence"]] == ["al_flow_sqli", "ev_flow_index"]
    assert context.providers.get("fake").requests[0].model == "granite4:micro"


def test_core_owns_ticket_id_specialist_and_question(tmp_path):
    """The queue's core check compares the finding's ticket_id with requester_id."""
    claimed = json.loads(response(VALID)) | {
        "ticket_id": "tk_another_ticket",
        "specialist": "cloud",
        "question": "A question nobody asked",
    }
    context = build_context(tmp_path, json.dumps(claimed), tickets=(TICKET,))

    finding = web_specialist(context)(REQUEST)

    assert finding["ticket_id"] == REQUEST["requester_id"]
    assert finding["specialist"] == "web"
    assert finding["question"] == QUESTION


def test_the_source_flow_is_read_through_the_web_allowlist(tmp_path):
    records = FakeReadOnlyRecords()
    analyze(tmp_path, VALID, tickets=(TICKET,), records=records)

    flow = [query for query in records.queries if query[0] == "event_id"]
    assert flow == [("event_id", "src_ip", "203.0.113.25", 1769998800000, 1770003000000, 200)]
    assert ("get_alert_record", "al_flow_sqli") in records.queries


def test_a_tool_outside_the_allowlist_fails_the_request(tmp_path):
    """The specialist reaches tools only through the server, so a missing grant stops it."""
    body = ALLOWED_TOOLS.replace('"get_alert", ', "")

    with pytest.raises(PermissionError):
        analyze(tmp_path, VALID, tickets=(TICKET,), body=body)


def test_malformed_output_falls_back_to_unknown(tmp_path):
    """docs/llm-policy.md 4: one retry, then succeeded unknown and confidence 0."""
    finding, context = analyze(tmp_path, MALFORMED, MALFORMED, tickets=(TICKET,))

    assert finding["succeeded"] == "unknown"
    assert finding["confidence"] == 0
    assert finding["needs_human"] is True
    assert finding["human_reason"]
    assert finding["evidence"]
    assert len(context.providers.get("fake").requests) == 2


def test_evidence_id_that_is_not_stored_falls_back_to_unknown(tmp_path):
    """A made-up reference is not retried: the finding cannot be checked at all."""
    finding, context = analyze(tmp_path, UNKNOWN_EVIDENCE, tickets=(TICKET,))

    assert finding["succeeded"] == "unknown"
    assert finding["confidence"] == 0
    assert finding["needs_human"] is True
    assert "ev_not_stored" not in str(finding)
    assert len(context.providers.get("fake").requests) == 1


def test_fallback_evidence_is_the_tickets_stored_alerts(tmp_path):
    finding, _ = analyze(tmp_path, MALFORMED, MALFORMED, tickets=(TICKET,))

    assert [item["ref_id"] for item in finding["evidence"]] == ["al_flow_scan", "al_flow_sqli"]
    assert {item["ref_type"] for item in finding["evidence"]} == {"alert"}


def test_a_ticket_without_stored_alerts_fails_the_request(tmp_path):
    """Nothing to cite means no C14 can be built: the queue fails it (D-034)."""
    ticket = TICKET | {"alert_ids": ["al_not_stored"]}

    with pytest.raises(LookupError):
        analyze(tmp_path, VALID, tickets=(ticket,))


def test_an_unknown_ticket_fails_the_request(tmp_path):
    with pytest.raises(TicketNotFoundError):
        analyze(tmp_path, VALID)


def test_every_step_is_logged_on_the_ticket(tmp_path):
    first = {
        "subject_type": "ticket",
        "subject_id": "tk_web_sample",
        "step": 1,
        "agent": "l1",
        "action": "decision",
        "tool": None,
        "prompt_version": None,
        "input_excerpt": "earlier step",
        "output_excerpt": "earlier step",
        "model": None,
        "tokens": None,
        "latency_ms": 1,
        "created_at": 1770001800000,
    }
    log = FakeAgentLog(first)

    analyze(tmp_path, VALID, tickets=(TICKET,), agent_log=log)

    steps = log.list_for_subject("ticket", "tk_web_sample")
    assert [step.step.step for step in steps] == [1, 2, 3, 4, 5, 6]
    mine = [step.step for step in steps if step.step.agent == WEB_AGENT]
    assert [step.action for step in mine] == [
        "tool_call",
        "tool_call",
        "tool_call",
        "llm_call",
        "decision",
    ]
    assert [step.tool for step in mine[:3]] == ["get_alert", "get_alert", "query_http_flow"]
    assert mine[3].prompt_version


def test_request_completes_through_the_queue(tmp_path):
    """Box 26 hands a specialist_agent request to box 14 and keeps the C14 result."""
    context = build_context(tmp_path, response(VALID), tickets=(TICKET,))
    queue = FakeEvidenceQueue()
    service = EvidenceQueueService(
        queue,
        mcp=context.settings.mcp,
        max_retries=0,
        handlers=default_handlers(context, _NoLookup()),
        tickets=context.tickets,
        clock=lambda: NOW,
    )
    queue.enqueue(REQUEST, agent=AGENT)

    done = service.process_next()

    assert done["status"] == "completed"
    assert done["result"]["finding"]["ticket_id"] == REQUEST["requester_id"]
    assert service.results_for("ticket", "tk_web_sample")[0]["status"] == "completed"


def test_a_request_without_a_domain_goes_to_the_web_specialist(tmp_path):
    """C22 requires a domain for a specialist request; a queue that drops it still lands on web."""
    context = build_context(tmp_path, response(VALID), tickets=(TICKET,))
    handler = default_handlers(context, _NoLookup())["specialist_agent"]

    result = handler(REQUEST | {"domain": None}, agent=AGENT)

    assert result["finding"]["specialist"] == "web"


def test_default_handlers_carry_the_specialist_handler(tmp_path):
    context = build_context(tmp_path)

    assert set(default_handlers(context, _NoLookup())) == {
        "siem_mcp",
        "lookup",
        "specialist_agent",
    }


def test_a_fake_specialist_replaces_web_by_registry(tmp_path):
    """The domain picks the implementation, so Cloud is one registration (13)."""
    registry = PluginRegistry("specialists")
    registry.register("web", lambda context: lambda request: {"specialist": "fake"})

    assert open_specialist("web", build_context(tmp_path), registry)(REQUEST) == {
        "specialist": "fake"
    }
    assert "web" in SPECIALISTS.names()


def test_the_flow_window_and_limit_come_from_the_settings(tmp_path):
    body = f"{ALLOWED_TOOLS}\n[specialist]\nflow_window_minutes = 1\nflow_limit = 3\n"
    records = FakeReadOnlyRecords()
    analyze(tmp_path, VALID, tickets=(TICKET,), records=records, body=body)

    flow = [query for query in records.queries if query[0] == "event_id"]
    assert flow == [("event_id", "src_ip", "203.0.113.25", 1770000540000, 1770001260000, 3)]


def test_the_flow_limit_never_exceeds_the_mcp_query_limit(tmp_path):
    body = f"{ALLOWED_TOOLS}\n[mcp]\nmax_query_limit = 2\n\n[specialist]\nflow_limit = 500\n"
    records = FakeReadOnlyRecords()
    analyze(tmp_path, VALID, tickets=(TICKET,), records=records, body=body)

    assert [query for query in records.queries if query[0] == "event_id"][0][-1] == 2


def test_default_settings_hold_the_specialist_section():
    specialist = default_settings().specialist

    assert specialist.flow_window_minutes >= 1
    assert specialist.flow_limit >= 1


# --- #91: flow rows and the input limit ------------------------------------------------

SCAN_ALERT_TIME = 1770000600000  # al_flow_scan in tests/fixtures/l1/mcp/internal_records.json


def run_on_flow(tmp_path, *, extra_4xx=0, body=ALLOWED_TOOLS):
    """The specialist over the demo-shaped flow; returns (finding, sent request, attack IDs)."""
    events, attack_ids = web_flow_events(SCAN_ALERT_TIME, extra_4xx=extra_4xx)
    records = FakeReadOnlyRecords(alerts=fixture_alerts(), events=events)
    finding, context = analyze(tmp_path, VALID, tickets=(TICKET,), records=records, body=body)
    requests = context.providers.get("fake").requests
    return finding, (requests[0] if requests else None), attack_ids


def sent_size(request):
    return len(request.system_prompt) + len(request.user_prompt)


def test_demo_shaped_flow_fits_and_keeps_the_upload_and_web_shell_lines(tmp_path):
    _finding, request, attack_ids = run_on_flow(tmp_path)

    assert sent_size(request) <= default_settings().l1.max_input_chars
    assert len(attack_ids) == 33
    assert all(event_id in request.user_prompt for event_id in attack_ids)
    assert '"columns":["event_id","time","http_url","http_status"]' in request.user_prompt


def test_a_long_flow_of_4xx_lines_still_keeps_the_upload_and_web_shell_lines(tmp_path):
    """4xx lines go first, so many scan errors near the alert cannot push the attack out."""
    _finding, request, attack_ids = run_on_flow(tmp_path, extra_4xx=110)

    assert sent_size(request) <= default_settings().l1.max_input_chars
    assert all(event_id in request.user_prompt for event_id in attack_ids)
    assert '"input_trimmed":true' in request.user_prompt


def test_flow_lines_leave_out_unmapped_method_agent_and_size(tmp_path):
    _finding, request, _ids = run_on_flow(tmp_path)

    assert "python-requests" not in request.user_prompt
    assert "unmapped" not in request.user_prompt


def test_input_over_the_limit_falls_back_without_calling_the_model(tmp_path):
    body = f"{ALLOWED_TOOLS}\n[l1]\nmax_input_chars = 1000\n"
    finding, request, _ids = run_on_flow(tmp_path, body=body)

    assert request is None
    assert finding["succeeded"] == "unknown"
    assert finding["confidence"] == 0
    assert finding["human_reason"] == INPUT_TOO_LARGE


def test_a_stored_event_outside_the_shown_flow_cannot_be_cited(tmp_path):
    """The prepared answer cites ev_flow_index: stored, but not in this flow (#91)."""
    finding, request, _ids = run_on_flow(tmp_path)

    assert request is not None
    assert finding["succeeded"] == "unknown"
    assert finding["confidence"] == 0


class _NoLookup:
    """The lookup handler is not what these tests exercise."""

    def find_asset(self, value, at):
        return None

    def find_user(self, user, at):
        return None
