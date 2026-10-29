"""Specialist Agent interface (boxes 13, 14, docs/extensibility.md).

A specialist answers one C22 ``specialist_agent`` request with a C14
SpecialistFinding. The queue (26) picks the implementation by the request's
``domain``, so a new domain is one registration and one module: the core never
names a specialist.

``SpecialistContext`` is what one specialist is built from, the same shape box 15
uses for its tool bundles: everything an agent may touch comes in from outside,
so a test can hand it fakes. Changing this interface breaks installed specialist
plugins, so it follows the contract change procedure (docs/data-contracts.md).
"""

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from soc.config import Settings
from soc.l1.agent_log import AgentLogService
from soc.l1.mcp.server import ToolServer
from soc.l1.tickets import TicketService
from soc.plugins import PluginRegistry
from soc.store.records.base import RecordStore


class NoStoredEvidenceError(LookupError):
    """Nothing a C14 could cite is stored, so no finding can be built at all."""


@dataclass(frozen=True, slots=True)
class SpecialistContext:
    """What one specialist is built from.

    ``tools`` is the only way to a tool, and the specialist calls it under its own
    agent name, not the requester's. ``records`` opens the read-only Alert/Event
    store on first use and is what evidence IDs are checked against
    (docs/llm-policy.md 4). ``providers`` overrides the LLM provider registry in
    tests; None means the process-wide one.
    """

    settings: Settings
    environ: Mapping[str, str]
    tools: ToolServer
    tickets: TicketService
    records: Callable[[], RecordStore]
    agent_log: AgentLogService
    providers: PluginRegistry | None = None


class Specialist(Protocol):
    def __call__(self, request: Mapping[str, Any]) -> dict[str, Any]:
        """One C22 ``specialist_agent`` request -> one C14 SpecialistFinding.

        Raises if no finding can be built; the queue then retries and finally
        fails the request (D-034).
        """
        ...


class SpecialistFactory(Protocol):
    """What an implementation registers in the ``specialists`` group."""

    def __call__(self, context: SpecialistContext) -> Specialist: ...
