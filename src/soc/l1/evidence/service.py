"""Evidence request queue worker (unnumbered, D-034, K59, K62).

One worker takes requests in arrival order and runs the handler registered for
each ``request_type``. A failed attempt is retried at once, up to
``evidence_queue.max_retries`` times, so a request keeps its place in line.
After the last retry the request is ``failed``:

- Ticket request: the Ticket goes on hold through box 18's transitions (D-034).
- Alert request: the failed request goes back to the requester as is. The hold
  record (C23 ``held`` / ``evidence_request_failure``) is boxes 15 and 20's job (D-036).

``failure_reason`` holds an error type name, never an error message: messages can
repeat log text an attacker wrote (docs/security-policy.md 3).
"""

import logging
import time
import uuid
from collections.abc import Callable, Mapping
from typing import Any

from soc.config import McpSettings, Settings
from soc.l1.evidence import open_evidence_queue
from soc.l1.tickets import TicketService
from soc.plugins import PluginRegistry

from .base import EvidenceHandler, EvidenceQueue
from .checks import check_request, check_result

logger = logging.getLogger(__name__)

# How a failed request puts its Ticket on hold, by the Ticket's status. Any other
# status (on_hold, closed_*, l2_escalated) is already settled and is left alone.
HOLD_PATH = {"new": ("triaging", "on_hold"), "triaging": ("on_hold",)}


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _new_request_id() -> str:
    return f"rq_{uuid.uuid4().hex}"


class EvidenceQueueService:
    def __init__(
        self,
        queue: EvidenceQueue,
        *,
        mcp: McpSettings,
        max_retries: int,
        handlers: Mapping[str, EvidenceHandler],
        tickets: TicketService,
        clock: Callable[[], int] = _now_ms,
        id_factory: Callable[[], str] = _new_request_id,
    ):
        self._queue = queue
        self._mcp = mcp
        self._max_retries = max_retries
        self._handlers = dict(handlers)
        self._tickets = tickets
        self._clock = clock
        self._id_factory = id_factory

    @classmethod
    def from_settings(
        cls,
        settings: Settings,
        *,
        handlers: Mapping[str, EvidenceHandler],
        tickets: TicketService,
        environ: Mapping[str, str] | None = None,
        registry: PluginRegistry | None = None,
    ) -> "EvidenceQueueService":
        return cls(
            open_evidence_queue(settings, environ=environ, registry=registry),
            mcp=settings.mcp,
            max_retries=settings.evidence_queue.max_retries,
            handlers=handlers,
            tickets=tickets,
        )

    @property
    def tickets(self) -> TicketService:
        return self._tickets

    def enqueue(
        self,
        *,
        agent: str,
        requester_type: str,
        requester_id: str,
        request_type: str,
        params: Mapping[str, Any],
        domain: str | None = None,
    ) -> dict[str, Any]:
        """Queue a new request after the C22 core checks. ``agent`` picks the MCP allowlist."""
        if not agent:
            raise ValueError("agent must name the agent that asks")
        now = self._clock()
        request = {
            "request_id": self._id_factory(),
            "requester_type": requester_type,
            "requester_id": requester_id,
            "request_type": request_type,
            "domain": domain,
            "params": dict(params),
            "retry_count": 0,
            "status": "pending",
            "failure_reason": None,
            "result": None,
            "created_at": now,
            "updated_at": now,
        }
        return self._queue.enqueue(check_request(request, self._mcp), agent=agent)

    def get(self, request_id: str) -> dict[str, Any] | None:
        return self._queue.get(request_id)

    def results_for(self, requester_type: str, requester_id: str) -> list[dict[str, Any]]:
        """Every request of one Alert or Ticket with its status and result, in arrival order."""
        return self._queue.list_by_requester(requester_type, requester_id)

    def start(self) -> int:
        """Return requests a stopped worker left ``in_progress`` to the line.

        Only safe while this is the only worker.
        """
        released = self._queue.release_in_progress(now_ms=self._clock())
        if released:
            logger.warning("Returned %d in-progress evidence requests to the queue", released)
        return released

    def run_until_empty(self) -> list[dict[str, Any]]:
        """Start as the only worker and process requests until none is pending."""
        self.start()
        done = []
        while (request := self.process_next()) is not None:
            done.append(request)
        return done

    def process_next(self) -> dict[str, Any] | None:
        """Process the oldest pending request to ``completed`` or ``failed``.

        Returns None when the queue is empty.
        """
        claimed = self._queue.claim_next(now_ms=self._clock())
        if claimed is None:
            return None
        request, agent = claimed.request, claimed.agent
        handler = self._handlers.get(request["request_type"])
        if handler is None:
            return self._fail(request, f"no handler for request_type {request['request_type']}")
        while True:
            try:
                completed = self._attempt(handler, request, agent)
            except Exception as error:  # Handlers are plugin code: any error is one failed try.
                reason = type(error).__name__
                if request["retry_count"] >= self._max_retries:
                    return self._fail(request, f"{reason} after {request['retry_count']} retries")
                logger.info("Retrying evidence request %s after %s", request["request_id"], reason)
                retry = request | {
                    "retry_count": request["retry_count"] + 1,
                    "updated_at": self._clock(),
                }
                request = self._queue.update(retry, expected_status="in_progress")
                continue
            return self._queue.update(completed, expected_status="in_progress")

    def _attempt(
        self, handler: EvidenceHandler, request: dict[str, Any], agent: str
    ) -> dict[str, Any]:
        result = handler(request, agent=agent)
        completed = request | {"status": "completed", "result": result, "updated_at": self._clock()}
        return check_result(completed)

    def _fail(self, request: dict[str, Any], reason: str) -> dict[str, Any]:
        failed = request | {
            "status": "failed",
            "failure_reason": reason,
            "updated_at": self._clock(),
        }
        failed = self._queue.update(failed, expected_status="in_progress")
        logger.warning("Evidence request %s failed: %s", failed["request_id"], reason)
        if failed["requester_type"] == "ticket":
            self._hold_ticket(failed["requester_id"])
        return failed

    def _hold_ticket(self, ticket_id: str) -> None:
        ticket = self._tickets.get(ticket_id)
        if ticket is None:
            logger.warning("Ticket %s not found: cannot hold it after a failed request", ticket_id)
            return
        path = HOLD_PATH.get(ticket["status"])
        if path is None:
            logger.info(
                "Ticket %s is %s: left as is after a failed request", ticket_id, ticket["status"]
            )
            return
        for status in path:
            self._tickets.transition(ticket_id, status)
