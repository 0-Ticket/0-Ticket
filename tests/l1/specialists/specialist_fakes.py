"""Test doubles for the Web specialist Agent (boxes 19, 31).

``FakeProvider`` answers every LLM call with a prepared string, so no model is
reached (docs/llm-policy.md 7). ``FakeAgentLog`` stands in for the Agent Log service:
it validates each C8 the same way and keeps the steps for assertions.
``build_context`` wires the real tool server and the real ``TicketService`` over
the in-memory fakes, so the specialist runs its production code path.
"""

import json
from pathlib import Path

from evidence_fakes import FakeTicketStore
from fake_records import FakeReadOnlyRecords
from fake_siem_mcp import org_settings

from soc.contracts import validate_contract
from soc.l1.agent_log import AgentLogEntry
from soc.l1.mcp.internal import internal_data_tools
from soc.l1.mcp.server import ToolContext, ToolServer
from soc.l1.mcp.web import web_tools
from soc.l1.specialists.base import SpecialistContext
from soc.l1.tickets import TicketService
from soc.llm.base import ProviderResponse
from soc.plugins import PluginRegistry

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = ROOT / "tests" / "fixtures" / "l1" / "specialists"
RESPONSES = ROOT / "tests" / "fixtures" / "llm" / "responses"
PROVIDER = "fake"

# The Web specialist's own allowlist (docs/extensibility.md), plus the agent that
# asks: the requester's name must not decide which tools the specialist may call.
ALLOWED_TOOLS = """[llm]
provider = "fake"

[mcp.allowed_tools]
l1 = ["query_siem"]
web_specialist = ["get_alert", "query_http_flow"]
"""

_UNSET = object()


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def response(name: str) -> str:
    return (RESPONSES / name).read_text(encoding="utf-8")


class FakeProvider:
    """Returns the prepared contents in order and records every request."""

    def __init__(self, *contents: str):
        self.contents = list(contents)
        self.requests = []

    def complete(self, request):
        self.requests.append(request)
        return ProviderResponse(content=self.contents.pop(0), tokens=11)


class FakeAgentLog:
    """Validates and keeps C8 steps; callable as ``call_llm(record_step=...)``."""

    def __init__(self, *steps):
        self.entries = [AgentLogEntry(step=validate_contract("AgentStep", s)) for s in steps]

    def __call__(self, step) -> None:
        self.record(step)

    def record(self, step, *, full_result=_UNSET) -> None:
        raw = step.model_dump(mode="json") if hasattr(step, "model_dump") else dict(step)
        if full_result is not _UNSET:
            raw["output_excerpt"] = json.dumps(full_result, ensure_ascii=False)[:2000]
        self.entries.append(AgentLogEntry(step=validate_contract("AgentStep", raw)))

    def list_for_subject(self, subject_type, subject_id):
        return [
            entry
            for entry in self.entries
            if entry.step.subject_type == subject_type and entry.step.subject_id == subject_id
        ]

    @property
    def steps(self):
        return [entry.step for entry in self.entries]


def build_context(
    tmp_path, *contents: str, body: str = ALLOWED_TOOLS, records=None, **wiring
) -> SpecialistContext:
    """A context whose LLM answers with ``contents`` and whose store holds the fixtures."""
    settings = org_settings(tmp_path, body)
    records = FakeReadOnlyRecords() if records is None else records
    tool_context = ToolContext(settings, {}, lambda: records)
    tools = ToolServer(settings.mcp, (*internal_data_tools(tool_context), *web_tools(tool_context)))
    return context_for(settings, tools, *contents, records=records, **wiring)


def context_for(
    settings, tools, *contents: str, tickets=(), records=None, agent_log=None
) -> SpecialistContext:
    """Wrap a tool server a test already built into a specialist context."""
    records = FakeReadOnlyRecords() if records is None else records
    providers = PluginRegistry("llm_providers")
    providers.register(PROVIDER, FakeProvider(*contents))
    return SpecialistContext(
        settings=settings,
        environ={},
        tools=tools,
        tickets=TicketService(FakeTicketStore(*tickets)),
        records=lambda: records,
        agent_log=FakeAgentLog() if agent_log is None else agent_log,
        providers=providers,
    )
