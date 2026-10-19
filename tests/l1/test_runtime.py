"""Box 11 entity lookup: evidence, Verdict, Ticket promotion, and C23 holds."""

import json
from pathlib import Path

import pytest
from evidence_fakes import FakeEvidenceQueue
from fake_branch_store import FakeBranchStore
from fake_l1_decision_store import FakeL1DecisionStore
from fake_store import FakeRecordStore
from fake_ticket_store import FakeTicketStore

from soc.config import load_config
from soc.contracts import validate_contract
from soc.ingest.connector import source_record_id
from soc.l1.agent_log import AgentLogEntry, AgentLogService
from soc.l1.evidence.service import EvidenceQueueService
from soc.l1.runtime import L1Runtime
from soc.l1.runtime import build_runtime as assemble_runtime
from soc.l1.tickets import TicketService
from soc.llm import CallContext, CallFailure, LLMCallResult
from soc.plugins import PluginRegistry
from soc.store.paging import DEFAULT_PAGE_LIMIT

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests" / "fixtures"
L1_FIXTURES = FIXTURES / "l1" / "entity_lookup"
NOW = 1791849700000
ALERT_ID = "al_sample_wpscan"
MINUTE_MS = 60_000


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def make_records():
    records = FakeRecordStore()
    source_data = read_json(FIXTURES / "contracts" / "valid" / "siem_alert.json")
    source_data["source_record_id"] = source_record_id(source_data)
    source = validate_contract("SiemAlert", source_data)
    records.save_source_records([source], "l1-test", None)

    alert_data = next(
        item
        for item in read_json(FIXTURES / "store" / "alert_records.json")
        if item["alert_id"] == ALERT_ID
    )
    alert_data["source_record_id"] = source.source_record_id
    alert = validate_contract("AlertRecord", alert_data)
    records.save_alert_record(alert)

    event_source_data = read_json(FIXTURES / "contracts" / "valid" / "siem_alert.json")
    event_source_data["kind"] = "event"
    event_source_data["source_record_id"] = source_record_id(event_source_data)
    event_source = validate_contract("SiemAlert", event_source_data)
    records.save_source_records([event_source], "l1-event-test", None)
    event_data = read_json(FIXTURES / "contracts" / "valid" / "event_record.json")
    event_data["source_record_id"] = event_source.source_record_id
    records.save_event_record(validate_contract("EventRecord", event_data))
    return records, alert


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


class FakeLLM:
    def __init__(self, response=None, failure=None):
        self.response = response
        self.failure = failure
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        context = kwargs["context"]
        output = self.response or {}
        step = validate_contract(
            "AgentStep",
            {
                "subject_type": context.subject_type,
                "subject_id": context.subject_id,
                "step": context.step,
                "agent": context.agent,
                "action": "llm_call",
                "tool": None,
                "prompt_version": "l1-entity-lookup-v1",
                "input_excerpt": "synthetic L1 input",
                "output_excerpt": json.dumps(output),
                "model": "fake-model",
                "tokens": 1,
                "latency_ms": 1,
                "created_at": NOW,
            },
        )
        kwargs["record_step"](step)
        if self.failure is not None:
            return LLMCallResult(value=None, failure=self.failure)
        return LLMCallResult(value=validate_contract("Verdict", output), failure=None)


class FakeVectorTickets:
    def __init__(self, results=(), error=None):
        self.results = list(results)
        self.error = error
        self.calls = []

    def search_by_entities(self, entities, sentence, *, k):
        self.calls.append((entities, sentence, k))
        if self.error is not None:
            raise self.error
        return self.results


def build_runtime(tmp_path, *, verdict=None, llm_failure=None, queue_failure=False, vector=None):
    settings = load_config(environ={})
    branch_store = FakeBranchStore()
    branch_store.save(validate_contract("BranchResult", read_json(L1_FIXTURES / "branch.json")))
    records, alert = make_records()
    decision_store = FakeL1DecisionStore()
    ticket_store = FakeTicketStore()
    tickets = TicketService(ticket_store, clock=lambda: NOW, id_factory=lambda: "tk_l1_test")
    queue = FakeEvidenceQueue()

    def lookup_handler(_request, *, agent):
        assert agent == "l1"
        if queue_failure:
            raise RuntimeError("synthetic queue failure")
        return {"asset": None, "user": None}

    def siem_handler(_request, *, agent):
        assert agent == "l1"
        if queue_failure:
            raise RuntimeError("synthetic queue failure")
        return {"records": []}

    evidence = EvidenceQueueService(
        queue,
        mcp=settings.mcp,
        max_retries=0,
        handlers={"lookup": lookup_handler, "siem_mcp": siem_handler},
        tickets=tickets,
        clock=lambda: NOW,
        id_factory=iter(f"rq_l1_{n}" for n in range(1, 20)).__next__,
    )
    log_store = MemoryAgentLogStore()
    agent_log = AgentLogService(log_store, tmp_path)
    llm = FakeLLM(response=verdict, failure=llm_failure)
    vector_tickets = vector or FakeVectorTickets()
    runtime = L1Runtime(
        settings=settings,
        branches=branch_store,
        decisions=decision_store,
        decision_reader=decision_store,
        records=records,
        tickets=tickets,
        ticket_reader=TicketService(ticket_store),
        evidence=evidence,
        vector_tickets=vector_tickets,
        agent_log=agent_log,
        llm_call=llm,
        clock=lambda: NOW,
        id_factory=iter(f"ld_l1_{n}" for n in range(1, 20)).__next__,
    )
    return runtime, {
        "settings": settings,
        "alert": alert,
        "branches": branch_store,
        "decisions": decision_store,
        "records": records,
        "tickets": tickets,
        "ticket_store": ticket_store,
        "queue": queue,
        "agent_log": log_store,
        "llm": llm,
        "vector": vector_tickets,
    }


def test_promotes_alert_and_queues_lookup_and_siem_with_five_minute_window(tmp_path):
    verdict = read_json(L1_FIXTURES / "promote.json")
    runtime, state = build_runtime(tmp_path, verdict=verdict)

    assert runtime.run(all_alerts=True) == 1

    decision = state["decisions"].get("alert", ALERT_ID)
    assert decision.decision == "l1_escalated"
    assert decision.confidence == 0.9
    ticket = state["tickets"].get("tk_l1_test")
    assert ticket["origin"] == "l1_escalated"
    assert ticket["handling_type"] == "web_attack"
    assert ticket["specialist"] == "web"
    assert ticket["entities"][0] == {"type": "ip", "value": "198.51.100.23"}

    requests = state["queue"].list_by_requester("alert", ALERT_ID)
    lookups = [item for item in requests if item["request_type"] == "lookup"]
    siem = [item for item in requests if item["request_type"] == "siem_mcp"]
    assert len(lookups) == 3
    assert len(siem) == 3
    assert all(item["params"]["at"] == state["alert"].time for item in lookups)
    assert all(item["params"]["kind"] == "alert" for item in siem)
    assert all(
        item["params"]["start_at"] == state["alert"].time - 5 * MINUTE_MS
        and item["params"]["end_at"] == state["alert"].time + 5 * MINUTE_MS
        and item["params"]["limit"] <= state["settings"].mcp.max_query_limit
        for item in siem
    )
    assert state["vector"].calls[0][2] == 5
    assert state["llm"].calls[0]["contract_name"] == "Verdict"
    assert state["llm"].calls[0]["context"] == CallContext(
        subject_type="alert", subject_id=ALERT_ID, step=3, agent="l1"
    )
    assert state["llm"].calls[0]["data"]["representative_entity"] == ticket["entities"][0]
    assert [entry.step.action for entry in state["agent_log"].entries] == [
        "tool_call",
        "tool_call",
        "llm_call",
        "decision",
    ]


def test_holds_tp_below_threshold_without_creating_ticket(tmp_path):
    runtime, state = build_runtime(
        tmp_path, verdict=read_json(L1_FIXTURES / "below_threshold.json")
    )

    runtime.run(all_alerts=True)

    decision = state["decisions"].get("alert", ALERT_ID)
    assert (decision.decision, decision.reason) == ("held", "below_threshold")
    assert state["ticket_store"].tickets == {}


def test_holds_when_llm_call_fails(tmp_path):
    runtime, state = build_runtime(
        tmp_path,
        llm_failure=CallFailure(path="/", rule="provider_error"),
    )

    runtime.run(all_alerts=True)

    decision = state["decisions"].get("alert", ALERT_ID)
    assert (decision.decision, decision.reason) == ("held", "llm_failure")
    assert state["ticket_store"].tickets == {}


def test_holds_on_failed_evidence_request_without_calling_llm(tmp_path):
    runtime, state = build_runtime(
        tmp_path,
        verdict=read_json(L1_FIXTURES / "promote.json"),
        queue_failure=True,
    )

    runtime.run(all_alerts=True)

    decision = state["decisions"].get("alert", ALERT_ID)
    assert (decision.decision, decision.reason) == ("held", "evidence_request_failure")
    assert state["llm"].calls == []
    assert state["ticket_store"].tickets == {}


def test_holds_when_verdict_cites_evidence_not_in_record_store(tmp_path):
    runtime, state = build_runtime(
        tmp_path,
        verdict=read_json(L1_FIXTURES / "unknown_evidence.json"),
    )

    runtime.run(all_alerts=True)

    decision = state["decisions"].get("alert", ALERT_ID)
    assert (decision.decision, decision.reason) == ("held", "llm_failure")
    assert state["ticket_store"].tickets == {}


def test_holds_when_verdict_cites_raw_id_not_linked_to_a_stored_record(tmp_path):
    runtime, state = build_runtime(
        tmp_path,
        verdict=read_json(L1_FIXTURES / "unknown_raw_evidence.json"),
    )

    runtime.run(all_alerts=True)

    decision = state["decisions"].get("alert", ALERT_ID)
    assert (decision.decision, decision.reason) == ("held", "llm_failure")


def test_accepts_event_evidence_from_the_readonly_record_store(tmp_path):
    runtime, state = build_runtime(
        tmp_path,
        verdict=read_json(L1_FIXTURES / "event_evidence.json"),
    )

    runtime.run(all_alerts=True)

    assert state["decisions"].get("alert", ALERT_ID).decision == "l1_escalated"


def test_accepts_raw_evidence_linked_from_a_stored_alert(tmp_path):
    runtime, state = build_runtime(
        tmp_path,
        verdict=read_json(L1_FIXTURES / "raw_evidence.json"),
    )

    runtime.run(all_alerts=True)

    assert state["decisions"].get("alert", ALERT_ID).decision == "l1_escalated"


@pytest.mark.parametrize("verdict_name", ["fp", "unknown"])
def test_holds_non_tp_verdicts_even_when_confidence_is_high(tmp_path, verdict_name):
    verdict = read_json(L1_FIXTURES / "promote.json")
    verdict["verdict"] = verdict_name
    verdict["confidence"] = 0.99
    runtime, state = build_runtime(tmp_path, verdict=verdict)

    runtime.run(all_alerts=True)

    decision = state["decisions"].get("alert", ALERT_ID)
    assert (decision.decision, decision.reason) == ("held", "below_threshold")
    assert state["ticket_store"].tickets == {}


def test_rerun_does_not_process_or_promote_the_alert_twice(tmp_path):
    runtime, state = build_runtime(tmp_path, verdict=read_json(L1_FIXTURES / "promote.json"))

    assert runtime.run(all_alerts=True) == 1
    assert runtime.run(all_alerts=True) == 0

    assert len(state["llm"].calls) == 1
    assert len(state["ticket_store"].tickets) == 1
    assert len(state["decisions"].list(subject_type="alert").items) == 1


def test_runtime_runs_ticket_triage_after_entity_lookup(tmp_path):
    runtime, state = build_runtime(tmp_path, verdict=read_json(L1_FIXTURES / "promote.json"))
    calls = []

    class TicketTriageStub:
        def run(self, *, all_tickets, limit):
            assert state["ticket_store"].get("tk_l1_test") is not None
            calls.append((all_tickets, limit))
            return 2

    runtime.ticket_triage = TicketTriageStub()

    assert runtime.run(all_alerts=True) == 3
    assert calls == [(True, DEFAULT_PAGE_LIMIT)]


def test_vector_store_failure_warns_and_continues_without_similar_tickets(tmp_path, caplog):
    vector = FakeVectorTickets(error=RuntimeError("synthetic backend error"))
    runtime, state = build_runtime(
        tmp_path,
        verdict=read_json(L1_FIXTURES / "promote.json"),
        vector=vector,
    )

    runtime.run(all_alerts=True)

    assert state["decisions"].get("alert", ALERT_ID).decision == "l1_escalated"
    assert state["llm"].calls[0]["data"]["similar_tickets"] == []
    assert "RuntimeError" in caplog.text


def test_ticket_created_before_a_missing_c23_is_reused(tmp_path):
    runtime, state = build_runtime(tmp_path, verdict=read_json(L1_FIXTURES / "promote.json"))
    existing = state["tickets"].create(
        state["alert"].model_dump(mode="json"),
        origin="l1_escalated",
        entities=[{"type": "ip", "value": "198.51.100.23"}],
        handling_type="web_attack",
        specialist="web",
    )

    runtime.run(all_alerts=True)

    assert len(state["ticket_store"].tickets) == 1
    assert state["decisions"].get("alert", ALERT_ID).decision == "l1_escalated"
    assert existing["ticket_id"] in state["ticket_store"].tickets


def test_build_runtime_uses_registered_readonly_and_writable_stores(tmp_path):
    settings_path = tmp_path / "organization.toml"
    settings_path.write_text('[store]\nbackend = "fake"\n', encoding="utf-8")
    settings = load_config(settings_path, environ={})
    opened = []
    branch_store = FakeBranchStore()
    decision_store = FakeL1DecisionStore()
    records, _ = make_records()
    ticket_store = FakeTicketStore()
    agent_log_store = MemoryAgentLogStore()
    stores = PluginRegistry("stores")
    for kind, value in (
        ("tickets", ticket_store),
        ("readonly_tickets", ticket_store),
        ("agent_log", agent_log_store),
        ("readonly_records", records),
        ("readonly_branches", branch_store),
        ("l1_decisions", decision_store),
        ("readonly_l1_decisions", decision_store),
    ):
        stores.register(
            f"fake.{kind}", lambda _settings, _env, k=kind, v=value: opened.append(k) or v
        )

    runtime = assemble_runtime(
        settings,
        environ={},
        store_registry=stores,
        tool_server_factory=lambda *_args: object(),
        lookup_factory=lambda *_args: object(),
        evidence_queue_factory=lambda *_args: FakeEvidenceQueue(),
        vector_ticket_factory=lambda *_args, **_kwargs: FakeVectorTickets(),
    )

    assert opened == [
        "tickets",
        "readonly_tickets",
        "agent_log",
        "readonly_records",
        "readonly_branches",
        "l1_decisions",
        "readonly_l1_decisions",
    ]
    runtime.close()
