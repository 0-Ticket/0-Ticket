"""Evidence request queue interface (box 26, D-034, docs/extensibility.md).

A queue keeps C22 EvidenceRequests in arrival order and hands each one to a
single worker. Besides C22 it keeps one thing outside the contract: the name of
the agent that queued the request, whose MCP allowlist the request is read with.

Every method takes and returns plain C22 dicts. Changing this interface breaks
installed queue plugins, so it follows the contract change procedure
(docs/data-contracts.md).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from soc.config import Settings

STATUSES = ("pending", "in_progress", "completed", "failed")


class EvidenceRequestRejected(ValueError):
    """A request or result breaks a C22 core check. The message names the rule, never values."""


class DuplicateRequestError(ValueError):
    """A request with this ``request_id`` is already queued."""


class RequestNotFoundError(LookupError):
    """No request has this ``request_id``."""


class RequestStateError(RuntimeError):
    """The request's status changed since the caller read it."""


@dataclass(frozen=True, slots=True)
class ClaimedRequest:
    """A request a worker took off the queue, now ``in_progress``."""

    request: dict[str, Any]
    agent: str


class EvidenceQueue(Protocol):
    def enqueue(self, request: Mapping[str, Any], *, agent: str) -> dict[str, Any]:
        """Store a valid C22 request at the end of the line.

        Raises ``DuplicateRequestError`` if the ID is taken.
        """
        ...

    def claim_next(self, *, now_ms: int) -> ClaimedRequest | None:
        """Take the oldest ``pending`` request and mark it ``in_progress``.

        A request is claimed by one caller only. Returns None when nothing is pending.
        """
        ...

    def update(self, request: Mapping[str, Any], *, expected_status: str) -> dict[str, Any]:
        """Replace a stored request if its status is still ``expected_status``.

        Raises ``RequestStateError`` if it is not.
        """
        ...

    def release_in_progress(self, *, now_ms: int) -> int:
        """Put every ``in_progress`` request back to ``pending``.

        Keeps each one's place in line. For a single worker that is starting up.
        Returns how many were released.
        """
        ...

    def get(self, request_id: str) -> dict[str, Any] | None: ...

    def list_by_requester(self, requester_type: str, requester_id: str) -> list[dict[str, Any]]:
        """The requests of one Alert or Ticket, in arrival order."""
        ...

    def close(self) -> None: ...


class EvidenceQueueFactory(Protocol):
    """What a backend registers in the ``evidence_queues`` registry."""

    def __call__(self, settings: Settings, environ: Mapping[str, str]) -> EvidenceQueue: ...


class EvidenceHandler(Protocol):
    """Answers one ``request_type``: returns the C22 ``result`` object or raises.

    ``agent`` is the agent that queued the request; a handler calling MCP tools
    must use that agent's allowlist.
    """

    def __call__(self, request: Mapping[str, Any], *, agent: str) -> Mapping[str, Any]: ...
