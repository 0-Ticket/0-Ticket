import hashlib
import json
from pathlib import Path

import pytest

from soc.config import load_config
from soc.contracts import validate_contract
from soc.l1.agent_log import (
    SUBJECT_TYPES,
    AgentLogEntry,
    AgentLogService,
    ArtifactReference,
    DuplicateAgentStepError,
)
from soc.l1.tickets import TicketNotFoundError
from soc.plugins import PluginRegistry

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/agent_log"
TICKETS = ROOT / "tests/fixtures/tickets"


def load_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def agent_step(**updates):
    return load_json(FIXTURES / "agent_step.json") | updates


class FakeAgentLogStore:
    def __init__(self):
        self.entries = []
        self.closed = False

    def save_step(self, step, artifact=None):
        key = (step.subject_type, step.subject_id, step.step)
        if any(
            (entry.step.subject_type, entry.step.subject_id, entry.step.step) == key
            for entry in self.entries
        ):
            raise DuplicateAgentStepError("Agent Log step already exists")
        self.entries.append(AgentLogEntry(step=step, artifact=artifact))

    def list_steps(self, subject_type, subject_id):
        return [
            entry
            for entry in self.entries
            if entry.step.subject_type == subject_type and entry.step.subject_id == subject_id
        ]

    def close(self):
        self.closed = True


class FakeTicketStore:
    def __init__(self, ticket):
        self.ticket = ticket
        self.closed = False

    def get(self, ticket_id):
        return self.ticket if self.ticket["ticket_id"] == ticket_id else None

    def close(self):
        self.closed = True


@pytest.mark.parametrize("subject_type", sorted(SUBJECT_TYPES))
@pytest.mark.parametrize("action", ["llm_call", "tool_call", "decision"])
def test_agent_log_callable_persists_contract_steps_by_subject(subject_type, action, tmp_path):
    store = FakeAgentLogStore()
    service = AgentLogService(store, tmp_path)
    subject_id = {
        "alert": "al_sample",
        "ticket": "tk_sample",
        "incident": "in_sample",
        "hunt": "ht_sample",
    }[subject_type]
    step = agent_step(
        subject_type=subject_type,
        subject_id=subject_id,
        action=action,
        tool="query_siem" if action == "tool_call" else None,
        prompt_version="l1-verdict-1" if action == "llm_call" else None,
    )

    service(validate_contract("AgentStep", step))

    entries = service.list_for_subject(subject_type, subject_id)
    assert len(entries) == 1
    assert entries[0].step.model_dump(mode="json") == step
    assert entries[0].artifact is None


def test_agent_log_keeps_excerpt_and_hashes_the_rest_of_a_large_result(tmp_path):
    store = FakeAgentLogStore()
    service = AgentLogService(store, tmp_path)
    result = "x" * 2000 + "large tool result remainder"

    service.record(agent_step(action="tool_call", tool="query_siem"), full_result=result)

    entry = store.entries[0]
    remainder = "large tool result remainder"
    digest = hashlib.sha256(remainder.encode("utf-8")).hexdigest()
    assert entry.step.output_excerpt == "x" * 2000
    assert entry.artifact == ArtifactReference(digest, f"sha256/{digest}.txt")
    assert (tmp_path / entry.artifact.path).read_text(encoding="utf-8") == remainder


def test_agent_log_redacts_secrets_in_contract_fields_and_artifacts(tmp_path):
    secret = "test-api-secret-value"
    store = FakeAgentLogStore()
    service = AgentLogService(store, tmp_path, secrets=(secret,))
    step = agent_step(input_excerpt=f"password={secret}", tool=f"query-{secret}")
    result = "x" * 2000 + f"\ntoken={secret}\nremaining result"

    service.record(step, full_result=result)

    entry = store.entries[0]
    assert secret not in entry.step.input_excerpt
    assert secret not in entry.step.tool
    assert secret not in entry.step.output_excerpt
    artifact_text = (tmp_path / entry.artifact.path).read_text(encoding="utf-8")
    assert secret not in artifact_text
    assert "[REDACTED]" in artifact_text


def test_agent_log_redacts_configured_environment_secrets(tmp_path):
    config_path = tmp_path / "organization.toml"
    config_path.write_text('[store]\nbackend = "fake"\n', encoding="utf-8")
    settings = load_config(config_path, environ={})
    environment = {
        "DATABASE_URL": "db-secret",
        "LLM_API_KEY": "llm-secret",
        "SIEM_TOKEN": "siem-secret",
    }
    store = FakeAgentLogStore()
    registry = PluginRegistry("stores")
    registry.register("fake.agent_log", lambda _settings, _env: store)
    service = AgentLogService.from_settings(settings, environ=environment, registry=registry)

    service.record(agent_step(input_excerpt="db-secret llm-secret siem-secret"))

    for secret in environment.values():
        assert secret not in store.entries[0].step.input_excerpt


def test_ticket_query_includes_linked_alert_steps_in_time_order(tmp_path):
    store = FakeAgentLogStore()
    ticket = load_json(TICKETS / "ticket.json")
    ticket_store = FakeTicketStore(ticket)
    service = AgentLogService(
        store,
        tmp_path,
        ticket_store_factory=lambda: ticket_store,
    )
    alert_id = ticket["alert_ids"][0]
    service.record(agent_step(subject_id=alert_id, step=1, created_at=100))
    service.record(
        agent_step(
            subject_type="ticket",
            subject_id=ticket["ticket_id"],
            step=1,
            created_at=300,
        )
    )
    service.record(agent_step(subject_id=alert_id, step=2, created_at=200))
    service.record(agent_step(subject_id="al_unrelated", created_at=50))

    entries = service.list_for_ticket(ticket["ticket_id"])

    assert [(entry.step.subject_type, entry.step.step) for entry in entries] == [
        ("alert", 1),
        ("alert", 2),
        ("ticket", 1),
    ]
    assert ticket_store.closed


def test_ticket_query_raises_for_missing_ticket_and_closes_store(tmp_path):
    ticket_store = FakeTicketStore(load_json(TICKETS / "ticket.json"))
    service = AgentLogService(
        FakeAgentLogStore(),
        tmp_path,
        ticket_store_factory=lambda: ticket_store,
    )

    with pytest.raises(TicketNotFoundError):
        service.list_for_ticket("tk_missing")

    assert ticket_store.closed
