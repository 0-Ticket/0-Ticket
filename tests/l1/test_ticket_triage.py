"""Box 11 Ticket triage with fixture C5/C6 and fake queue, LLM and vector services."""

import json
from pathlib import Path

import pytest
from evidence_fakes import FakeEvidenceQueue
from fake_l1_decision_store import FakeL1DecisionStore
from fake_ticket_store import FakeTicketStore
from llm_input_fakes import siem_alerts

from soc.config import load_config
from soc.contracts import validate_contract
from soc.l1.agent_log import AgentLogEntry, AgentLogService
from soc.l1.evidence.service import EvidenceQueueService
from soc.l1.ticket_triage import L1TicketTriage
from soc.l1.tickets import TicketService
from soc.l1.vector_search import UnavailableTicketSearch
from soc.llm import CallFailure, LLMCallResult
from soc.llm.prompts import format_untrusted_data, load_prompt

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
TRIAGE_FIXTURES = FIXTURES / "l1" / "ticket_triage"
TICKET_ID = "tk_ticket_triage_web"
ALERT_ID = "al_sample_wpscan"
NOW = 1791849700000


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


class MemoryAgentLogStore:
    def __init__(self):
        self.entries = []

    def save_step(self, step, artifact=None):
        self.entries.append(AgentLogEntry(step=step, artifact=artifact))

    def list_steps(self, subject_type, subject_id):
        return [
            entry
            for entry in self.entries
            if entry.step.subject_type == subject_type and entry.step.subject_id == subject_id
        ]

    def close(self):
        pass


class FakeRecords:
    def __init__(self):
        alert_data = next(
            item
            for item in read_json(FIXTURES / "store" / "alert_records.json")
            if item["alert_id"] == ALERT_ID
        )
        self.alerts = {ALERT_ID: validate_contract("AlertRecord", alert_data)}
        event_data = read_json(FIXTURES / "contracts" / "valid" / "event_record.json")
        self.events = {event_data["event_id"]: validate_contract("EventRecord", event_data)}

    def get_alert_record(self, alert_id):
        return self.alerts.get(alert_id)

    def get_event_record(self, event_id):
        return self.events.get(event_id)


class FakeLLM:
    def __init__(self, verdict=None, failure=None):
        self.verdict = verdict
        self.failure = failure
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        context = kwargs["context"]
        step = validate_contract(
            "AgentStep",
            {
                "subject_type": context.subject_type,
                "subject_id": context.subject_id,
                "step": context.step,
                "agent": context.agent,
                "action": "llm_call",
                "tool": None,
                "prompt_version": "l1-ticket-triage-v3",
                "input_excerpt": "synthetic ticket triage input",
                "output_excerpt": json.dumps(self.verdict),
                "model": "fake-model",
                "tokens": 1,
                "latency_ms": 1,
                "created_at": NOW,
            },
        )
        kwargs["record_step"](step)
        if self.failure is not None:
            return LLMCallResult(value=None, failure=self.failure)
        return LLMCallResult(
            value=validate_contract("Verdict", self.verdict),
            failure=None,
        )


class FakeVectorTickets:
    def __init__(self, matches=(), error=None):
        self.matches = list(matches)
        self.error = error
        self.search_calls = []
        self.indexed = []

    def search_by_ticket(self, ticket, *, k):
        self.search_calls.append((ticket, k))
        if self.error is not None:
            raise self.error
        return self.matches

    def add_decided_ticket(self, ticket):
        if self.error is not None:
            raise self.error
        self.indexed.append(ticket)

    def close(self):
        pass


def build_triage(
    tmp_path,
    *,
    ticket_name="ticket_web.json",
    verdict_name="verdict_fp.json",
    llm_failure=None,
    queue_failure=False,
    vector=None,
    confidence_threshold=None,
    finding_evidence=None,
    siem=None,
    ticket_alerts=None,
    l1=None,
):
    """``siem`` is what the SIEM MCP returns; ``ticket_alerts`` replaces the Ticket's alerts."""
    settings = load_config(environ={})
    if l1 is not None:
        settings = settings.model_copy(update={"l1": settings.l1.model_copy(update=l1)})
    if confidence_threshold is not None:
        settings = settings.model_copy(
            update={
                "l1": settings.l1.model_copy(update={"confidence_threshold": confidence_threshold})
            }
        )
    ticket_store = FakeTicketStore()
    ticket_data = read_json(TRIAGE_FIXTURES / ticket_name)
    records = FakeRecords()
    siem_contents = []
    if siem is not None:
        siem_contents, _sources, siem_records = siem
        records.alerts.update({alert.alert_id: alert for alert in siem_records})
    if ticket_alerts is not None:
        records.alerts.update({alert.alert_id: alert for alert in ticket_alerts})
        ticket_data["alert_ids"] = [alert.alert_id for alert in ticket_alerts]
    ticket_store.create(ticket_data)
    tickets = TicketService(ticket_store, clock=lambda: NOW)
    queue = FakeEvidenceQueue()

    def specialist_handler(request, *, agent):
        assert agent == "l1"
        if queue_failure:
            raise RuntimeError("synthetic evidence failure")
        finding = read_json(FIXTURES / "l1" / "evidence" / "specialist_finding.json")
        finding.update(
            ticket_id=request["requester_id"],
            question=request["params"]["question"],
            evidence=finding_evidence
            or [{"ref_type": "alert", "ref_id": ALERT_ID, "note": "Stored ticket alert."}],
            created_at=NOW,
        )
        return {"finding": finding}

    def lookup_handler(_request, *, agent):
        assert agent == "l1"
        if queue_failure:
            raise RuntimeError("synthetic evidence failure")
        return {"asset": None, "user": None}

    def siem_handler(_request, *, agent):
        assert agent == "l1"
        if queue_failure:
            raise RuntimeError("synthetic evidence failure")
        return {"records": siem_contents}

    evidence = EvidenceQueueService(
        queue,
        mcp=settings.mcp,
        max_retries=0,
        handlers={
            "specialist_agent": specialist_handler,
            "lookup": lookup_handler,
            "siem_mcp": siem_handler,
        },
        tickets=tickets,
        clock=lambda: NOW,
        id_factory=iter(f"rq_triage_{i}" for i in range(1, 20)).__next__,
    )
    decision_store = FakeL1DecisionStore()
    agent_log_store = MemoryAgentLogStore()
    agent_log = AgentLogService(agent_log_store, tmp_path)
    verdict = read_json(TRIAGE_FIXTURES / verdict_name)
    llm = FakeLLM(verdict=verdict, failure=llm_failure)
    vector_tickets = vector or FakeVectorTickets()
    triage = L1TicketTriage(
        settings=settings,
        tickets=tickets,
        ticket_reader=TicketService(ticket_store),
        records=records,
        evidence=evidence,
        decisions=decision_store,
        vector_tickets=vector_tickets,
        agent_log=agent_log,
        llm_call=llm,
        clock=lambda: NOW,
        id_factory=iter(f"ld_triage_{i}" for i in range(1, 20)).__next__,
    )
    return triage, {
        "settings": settings,
        "ticket_store": ticket_store,
        "queue": queue,
        "decisions": decision_store,
        "agent_log": agent_log_store,
        "llm": llm,
        "vector": vector_tickets,
        "ticket": ticket_data,
    }


def test_fp_at_threshold_closes_and_stores_verdict_and_indexes_ticket(tmp_path):
    triage, state = build_triage(tmp_path)

    assert triage.run(all_tickets=True) == 1

    ticket = state["ticket_store"].get(TICKET_ID)
    assert ticket["status"] == "closed_fp"
    assert ticket["verdict"]["verdict"] == "fp"
    assert ticket["verdict"]["needs_human"] is True
    decision = state["decisions"].get("ticket", TICKET_ID)
    assert (decision.decision, decision.confidence, decision.reason) == ("closed_fp", 0.95, None)
    assert [item["ticket_id"] for item in state["vector"].indexed] == [TICKET_ID]
    assert state["llm"].calls[0]["contract_name"] == "Verdict"
    assert state["llm"].calls[0]["context"].subject_type == "ticket"
    assert state["llm"].calls[0]["context"].subject_id == TICKET_ID
    assert state["llm"].calls[0]["context"].agent == "l1"
    assert state["llm"].calls[0]["data"]["finding"]["ticket_id"] == TICKET_ID
    requests = state["queue"].list_by_requester("ticket", TICKET_ID)
    assert requests[0]["request_type"] == "specialist_agent"
    assert requests[0]["domain"] == "web"
    assert requests[0]["params"]["question"] == (
        "Did the activity represented by this Ticket indicate a successful attack? "
        "State what the evidence shows."
    )
    assert all(entry.step.subject_type == "ticket" for entry in state["agent_log"].entries)
    assert {entry.step.action for entry in state["agent_log"].entries} == {
        "decision",
        "tool_call",
        "llm_call",
    }


@pytest.mark.parametrize(
    ("verdict_name", "status", "decision", "reason"),
    [
        ("verdict_tp.json", "l2_escalated", "l2_escalated", None),
        ("verdict_below_threshold.json", "on_hold", "held", "below_threshold"),
    ],
)
def test_verdict_maps_to_l2_or_hold_without_a_benign_close(
    tmp_path, verdict_name, status, decision, reason
):
    triage, state = build_triage(tmp_path, verdict_name=verdict_name)

    triage.run(all_tickets=True)

    ticket = state["ticket_store"].get(TICKET_ID)
    assert ticket["status"] == status
    assert ticket["verdict"] is not None
    assert state["decisions"].get("ticket", TICKET_ID).decision == decision
    assert state["decisions"].get("ticket", TICKET_ID).reason == reason


def test_unknown_at_high_confidence_is_held_as_below_threshold(tmp_path):
    triage, state = build_triage(tmp_path, verdict_name="verdict_below_threshold.json")
    state["llm"].verdict["verdict"] = "unknown"
    state["llm"].verdict["confidence"] = 0.99

    triage.run(all_tickets=True)

    ticket = state["ticket_store"].get(TICKET_ID)
    assert ticket["status"] == "on_hold"
    assert ticket["verdict"]["verdict"] == "unknown"
    assert state["decisions"].get("ticket", TICKET_ID).reason == "below_threshold"


def test_configured_threshold_changes_the_ticket_branch(tmp_path):
    triage, state = build_triage(tmp_path, confidence_threshold=0.96)

    triage.run(all_tickets=True)

    assert state["ticket_store"].get(TICKET_ID)["status"] == "on_hold"
    assert state["decisions"].get("ticket", TICKET_ID).reason == "below_threshold"


def test_decided_ticket_similarity_is_included_and_open_tickets_are_filtered(tmp_path):
    vector = FakeVectorTickets(matches=[("tk_previous_decided", 0.95), ("tk_open", 0.8)])
    triage, state = build_triage(tmp_path, vector=vector)
    previous = read_json(FIXTURES / "tickets" / "ticket.json")
    previous.update(
        ticket_id="tk_previous_decided",
        status="closed_fp",
        verdict=read_json(TRIAGE_FIXTURES / "verdict_fp.json"),
    )
    open_ticket = previous | {
        "ticket_id": "tk_open",
        "origin": "l3_escalated",
        "status": "new",
        "verdict": None,
    }
    state["ticket_store"].create(previous)
    state["ticket_store"].create(open_ticket)

    triage.run(all_tickets=True)

    context = state["llm"].calls[0]["data"]["similar_tickets"]
    assert [item["ticket"]["ticket_id"] for item in context] == ["tk_previous_decided"]
    assert vector.search_calls[0][1] == state["settings"].l1.similar_tickets


def test_failed_evidence_request_holds_without_calling_llm(tmp_path):
    triage, state = build_triage(tmp_path, queue_failure=True)

    triage.run(all_tickets=True)

    ticket = state["ticket_store"].get(TICKET_ID)
    assert ticket["status"] == "on_hold"
    assert ticket["verdict"] is None
    assert state["llm"].calls == []
    decision = state["decisions"].get("ticket", TICKET_ID)
    assert (decision.decision, decision.reason, decision.confidence) == (
        "held",
        "evidence_request_failure",
        None,
    )


def test_llm_failure_holds_without_human_routing(tmp_path):
    triage, state = build_triage(
        tmp_path,
        llm_failure=CallFailure(path="/", rule="provider_error"),
    )

    triage.run(all_tickets=True)

    assert state["ticket_store"].get(TICKET_ID)["status"] == "on_hold"
    assert state["decisions"].get("ticket", TICKET_ID).reason == "llm_failure"
    assert state["vector"].indexed == []


def test_ticket_without_specialist_queues_only_lookup_and_siem_context(tmp_path):
    triage, state = build_triage(
        tmp_path,
        ticket_name="ticket_without_specialist.json",
        verdict_name="verdict_tp.json",
    )

    triage.run(all_tickets=True)

    requests = state["queue"].list_by_requester("ticket", "tk_ticket_triage_no_specialist")
    assert [item["request_type"] for item in requests] == [
        "lookup",
        "siem_mcp",
        "lookup",
        "siem_mcp",
    ]
    assert all(item["domain"] is None for item in requests)
    assert state["llm"].calls[0]["data"]["finding"] is None
    shown = state["llm"].calls[0]["data"]["evidence_requests"]
    assert [item["request_id"] for item in shown] == [item["request_id"] for item in requests]
    assert [item["result"] for item in shown if item["request_type"] == "lookup"] == [
        item["result"] for item in requests if item["request_type"] == "lookup"
    ]


def test_invalid_evidence_reference_holds_instead_of_saving_verdict(tmp_path):
    triage, state = build_triage(tmp_path)
    invalid = read_json(TRIAGE_FIXTURES / "verdict_fp.json")
    invalid["evidence"][0]["ref_id"] = "al_not_stored"
    state["llm"].verdict = invalid

    triage.run(all_tickets=True)

    assert state["ticket_store"].get(TICKET_ID)["status"] == "on_hold"
    assert state["ticket_store"].get(TICKET_ID)["verdict"] is None
    assert state["decisions"].get("ticket", TICKET_ID).reason == "llm_failure"


@pytest.mark.parametrize(
    ("ref_type", "ref_id", "finding_evidence"),
    [
        ("raw", "raw_suricata_eve.jsonl_1", None),
        (
            "event",
            "ev_sample",
            [{"ref_type": "event", "ref_id": "ev_sample", "note": "Stored event."}],
        ),
    ],
)
def test_verdict_accepts_stored_raw_and_specialist_event_evidence(
    tmp_path, ref_type, ref_id, finding_evidence
):
    triage, state = build_triage(tmp_path, finding_evidence=finding_evidence)
    state["llm"].verdict["evidence"] = [
        {"ref_type": ref_type, "ref_id": ref_id, "note": "Stored evidence."}
    ]

    triage.run(all_tickets=True)

    assert state["ticket_store"].get(TICKET_ID)["status"] == "closed_fp"
    assert state["decisions"].get("ticket", TICKET_ID).decision == "closed_fp"


def test_failed_vector_index_only_warns_after_decision(tmp_path, caplog):
    vector = FakeVectorTickets(error=RuntimeError("synthetic vector failure"))
    triage, state = build_triage(tmp_path, vector=vector)

    triage.run(all_tickets=True)

    assert state["ticket_store"].get(TICKET_ID)["status"] == "closed_fp"
    assert state["decisions"].get("ticket", TICKET_ID).decision == "closed_fp"
    assert "RuntimeError" in caplog.text


def test_l3_escalated_ticket_is_not_processed(tmp_path):
    triage, state = build_triage(tmp_path)
    ticket = state["ticket"] | {"origin": "l3_escalated"}
    state["ticket_store"].tickets[TICKET_ID] = ticket

    assert triage.run(all_tickets=True) == 0
    assert state["ticket_store"].get(TICKET_ID)["status"] == "new"
    assert state["llm"].calls == []


# --- #91: summarized evidence and the input limit -------------------------------------

NO_SPECIALIST = "tk_ticket_triage_no_specialist"


def llm_input_size(call):
    return len(load_prompt(call["prompt_path"]).text) + len(format_untrusted_data(call["data"]))


def test_demo_sized_ticket_input_stays_under_the_limit(tmp_path):
    """Two SIEM queries of 500 alerts each still make one call under max_input_chars."""
    triage, state = build_triage(
        tmp_path,
        ticket_name="ticket_without_specialist.json",
        verdict_name="verdict_tp.json",
        siem=siem_alerts(),
    )

    triage.run(all_tickets=True)

    call = state["llm"].calls[0]
    assert llm_input_size(call) <= state["settings"].l1.max_input_chars
    summaries = [
        item["result"]
        for item in call["data"]["evidence_requests"]
        if item["request_type"] == "siem_mcp"
    ]
    assert [summary["total"] for summary in summaries] == [500, 500]
    assert state["ticket_store"].get(NO_SPECIALIST)["status"] == "l2_escalated"


def test_many_ticket_alerts_are_summarized_and_hidden_ones_cannot_be_cited(tmp_path):
    _contents, _sources, alerts = siem_alerts(count=40)
    triage, state = build_triage(tmp_path, ticket_alerts=alerts, l1={"summary_records": 3})
    shown_ids = set()

    def remember_shown(**kwargs):
        shown_ids.update(item["alert_id"] for item in kwargs["data"]["alerts"]["records"])
        hidden = next(alert.alert_id for alert in alerts if alert.alert_id not in shown_ids)
        llm.verdict["evidence"] = [{"ref_type": "alert", "ref_id": hidden, "note": "Hidden."}]
        return original(**kwargs)

    llm = state["llm"]
    original = llm.__call__
    triage.llm_call = remember_shown

    triage.run(all_tickets=True)

    data = llm.calls[0]["data"]
    assert data["alerts"]["total"] == 40
    assert len(data["alerts"]["records"]) == 3
    assert data["ticket"]["alert_count"] == 40
    assert "alert_ids" not in data["ticket"]
    assert state["ticket_store"].get(TICKET_ID)["status"] == "on_hold"
    assert state["decisions"].get("ticket", TICKET_ID).reason == "llm_failure"


def test_ticket_input_still_over_the_limit_is_held_without_calling_the_llm(tmp_path):
    triage, state = build_triage(tmp_path, l1={"max_input_chars": 1000})

    triage.run(all_tickets=True)

    assert state["llm"].calls == []
    assert state["ticket_store"].get(TICKET_ID)["status"] == "on_hold"
    decision = state["decisions"].get("ticket", TICKET_ID)
    assert (decision.decision, decision.reason) == ("held", "llm_failure")


# --- #105: the search path disabled by an initialization failure ----------------------


def triage_steps(state, tool):
    return [
        entry.step.output_excerpt for entry in state["agent_log"].entries if entry.step.tool == tool
    ]


def test_search_disabled_by_initialization_failure_is_recorded_as_unavailable(tmp_path):
    triage, state = build_triage(tmp_path, vector=UnavailableTicketSearch())

    assert triage.run(all_tickets=True) == 1

    assert triage_steps(state, "vector_ticket_search") == ['{"unavailable":true}']
    assert state["llm"].calls[0]["data"]["similar_tickets"] == []


def test_a_normal_empty_search_is_recorded_as_count_zero(tmp_path):
    triage, state = build_triage(tmp_path, vector=FakeVectorTickets())

    assert triage.run(all_tickets=True) == 1

    assert triage_steps(state, "vector_ticket_search") == ['{"count":0}']


def test_a_search_failure_during_triage_is_recorded_as_failed(tmp_path):
    triage, state = build_triage(
        tmp_path, vector=FakeVectorTickets(error=RuntimeError("synthetic search failure"))
    )

    assert triage.run(all_tickets=True) == 1

    assert triage_steps(state, "vector_ticket_search") == ['{"failed":true}']


def test_unavailable_indexing_does_not_change_the_decided_ticket_or_its_decision(tmp_path):
    """#105: a C19 index that cannot run leaves the C6 status and the C23 record as decided."""
    triage, state = build_triage(tmp_path, vector=UnavailableTicketSearch())

    assert triage.run(all_tickets=True) == 1

    ticket = state["ticket_store"].get(TICKET_ID)
    assert ticket["status"] == "closed_fp"
    assert ticket["verdict"]["verdict"] == "fp"
    decision = state["decisions"].get("ticket", TICKET_ID)
    assert (decision.decision, decision.confidence, decision.reason) == ("closed_fp", 0.95, None)
    assert triage_steps(state, "vector_ticket_index") == ['{"unavailable":true}']


def test_evidence_failure_still_holds_when_the_search_is_unavailable(tmp_path):
    """D-034: the search state does not change the evidence-request hold."""
    triage, state = build_triage(tmp_path, queue_failure=True, vector=UnavailableTicketSearch())

    triage.run(all_tickets=True)

    assert state["ticket_store"].get(TICKET_ID)["status"] == "on_hold"
    decision = state["decisions"].get("ticket", TICKET_ID)
    assert (decision.decision, decision.reason) == ("held", "evidence_request_failure")


def test_llm_failure_still_holds_when_the_search_is_unavailable(tmp_path):
    """D-036: the search state does not change the LLM-failure hold."""
    triage, state = build_triage(
        tmp_path,
        llm_failure=CallFailure(rule="invalid_json", path=None),
        vector=UnavailableTicketSearch(),
    )

    triage.run(all_tickets=True)

    assert state["ticket_store"].get(TICKET_ID)["status"] == "on_hold"
    decision = state["decisions"].get("ticket", TICKET_ID)
    assert (decision.decision, decision.reason) == ("held", "llm_failure")
