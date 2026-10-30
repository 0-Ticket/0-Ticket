"""SIEM MCP adapter interface (boxes 28, 42, D-035, D-037, docs/extensibility.md).

An adapter answers one neutral query -- an entity, a time window and a kind --
by translating it into its own SIEM's query language. It only reads: there is no
write or response method here, and ``READ_ONLY_METHODS`` is what an adapter may
expose. Results are C2 SiemAlert content without ``source_record_id``, which the
core assigns through ``to_c2_records``, exactly as the ingest entry does (SIEM connector).

A query that fails raises one of two errors, so a caller (and the evidence queue's
``failure_reason``, which keeps the error type name) can tell why without the
SIEM's name: ``SiemUnavailableError`` when the SIEM cannot be reached,
``SiemAdapterError`` when it answered but the answer cannot be used, which
includes records the adapter returned that do not convert to C2. Their
messages name the failure only, never a query value, log content or secret, and
the ``query_siem`` tool replaces them with fixed messages anyway: only the type
leaves the tool.

Changing this interface breaks installed adapters, so it follows the contract
change procedure (docs/data-contracts.md).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from soc.config import SiemSettings
from soc.contracts import Entity
from soc.ingest.connector import to_c2
from soc.ingest.siem.base import HealthStatus

KINDS = ("alert", "event")
# What an adapter may expose. A response action (blocking, isolating) belongs to
# the approval path (docs/security-policy.md 4), never to a tool an agent can call.
READ_ONLY_METHODS = frozenset({"query", "health_check"})


class SiemUnavailableError(RuntimeError):
    """The SIEM cannot be reached: no connection, no answer in time, files unreadable."""


class SiemAdapterError(RuntimeError):
    """The SIEM answered, but the answer cannot be used as C2 records.

    The tool raises it as well when records the adapter returned fail C2 conversion.

    The tool also raises this for any other exception from adapter code. Either
    way it carries a fixed message, because adapter messages are plugin text.
    """


@dataclass(frozen=True, slots=True)
class SiemQuery:
    """One read of a SIEM: which entity, which window, alerts or events.

    Times are UTC epoch milliseconds and the window includes both ends.
    ``limit`` is the most records to return; the server caps it with
    ``mcp.max_query_limit`` before an adapter ever sees the query.
    """

    entity: Entity
    kind: Literal["alert", "event"]
    start_at: int
    end_at: int
    limit: int

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}")
        if self.end_at < self.start_at:
            raise ValueError("end_at must not be before start_at")
        if self.limit < 1:
            raise ValueError("limit must be at least 1")


def to_c2_records(records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Turn adapter content into stored C2 rows by assigning each source_record_id.

    The same record read through the SIEM MCP and through ingest gets the same ID,
    because both go through the one core function that computes it.
    """
    return [to_c2(record).model_dump(mode="json") for record in records]


class SiemMcpAdapter(Protocol):
    def query(self, query: SiemQuery) -> Sequence[Mapping[str, Any]]:
        """Return at most ``query.limit`` C2 contents matching the query.

        An entity type this SIEM does not hold is not an error: return nothing.
        Raises ``SiemUnavailableError`` or ``SiemAdapterError`` when the query fails.
        """
        ...

    def health_check(self) -> HealthStatus:
        """Report whether the SIEM can be reached. Report failure, do not raise it."""
        ...


class SiemMcpAdapterFactory(Protocol):
    """What an adapter registers in the ``siem_mcp_adapters`` registry.

    Address and options come from ``settings``; secrets are read from ``environ``
    through ``soc.config.read_secret(settings.token_env, environ)``. The same
    ``siem.adapter`` name selects the connector (unnumbered) and this adapter (D-037).
    """

    def __call__(self, settings: SiemSettings, environ: Mapping[str, str]) -> SiemMcpAdapter: ...
