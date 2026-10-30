"""The screen API of the web screens: read-only L1 results (D-027, docs/api-contracts.md).

Six GET paths and nothing else. There is no path that changes an L1 result:
people read promotions, holds, verdicts and failed evidence requests here, and
the only human approval in v2 is box 36 (docs/architecture.md). Five paths serve
the L1 result read; ``/api/metrics`` serves the F6 dashboard and has no aggregate to serve yet.

The five paths that read take their stores from a dependency that borrows one
connection for the request and gives it back when it ends (#104). ``/api/metrics``
reads nothing, so it borrows nothing.
"""

import logging
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from soc.api.readers import ApiReaderPool, ApiReaders
from soc.contracts import ContractValidationError
from soc.store.paging import DEFAULT_PAGE_LIMIT

from .responses import as_json, drain, error, findings_of, not_found, page

logger = logging.getLogger(__name__)


def create_app(reader_pool: ApiReaderPool) -> FastAPI:
    """The app serving from ``reader_pool``, which it opens and closes with itself."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        # Fails the start if the database cannot be reached, instead of answering
        # every request with an internal error.
        reader_pool.open()
        try:
            yield
        finally:
            reader_pool.close()

    def borrow_readers() -> Iterator[ApiReaders]:
        """One request's stores. FastAPI ends the generator when the request ends,
        however it ends, and the connection goes back then."""
        with reader_pool.readers() as readers:
            yield readers

    Readers = Annotated[ApiReaders, Depends(borrow_readers)]

    app = FastAPI(title="0-Ticket SOC screen API", lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def _invalid_request(request: Request, exc: RequestValidationError) -> JSONResponse:
        # One error shape for the screen: a bad query value is invalid_input, not 422.
        return error("invalid_input", "a query or path value is not valid")

    @app.exception_handler(ContractValidationError)
    async def _stored_object_is_invalid(
        request: Request, exc: ContractValidationError
    ) -> JSONResponse:
        # A stored object that no longer matches its contract is a server problem.
        logger.error("stored object failed contract validation: %s", exc)
        return error("internal", "internal error")

    @app.exception_handler(ValueError)
    async def _invalid_value(request: Request, exc: ValueError) -> JSONResponse:
        return error("invalid_input", str(exc))

    @app.exception_handler(Exception)
    async def _unexpected(request: Request, exc: Exception) -> JSONResponse:
        # The reason may quote stored data or a connection string; it stays in the log.
        logger.exception("unexpected error serving %s", request.url.path)
        return error("internal", "internal error")

    @app.get("/api/tickets")
    def list_tickets(
        readers: Readers,
        status: str | None = None,
        origin: str | None = None,
        handling_type: str | None = None,
        min_priority: int | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_LIMIT,
    ):
        result = readers.tickets.list(
            status=status,
            origin=origin,
            handling_type=handling_type,
            min_priority=min_priority,
            cursor=cursor,
            limit=limit,
        )
        return page(result.items, result.next_cursor)

    @app.get("/api/tickets/{ticket_id}")
    def get_ticket(ticket_id: str, readers: Readers):
        ticket = readers.tickets.get(ticket_id)
        if ticket is None:
            return not_found("ticket")
        requests = readers.evidence_queue.list_by_requester("ticket", ticket_id)
        alerts = (readers.records.get_alert_record(alert_id) for alert_id in ticket["alert_ids"])
        return {
            "ticket": as_json(ticket),
            # An alert_id with no stored Alert is left out; it stays in ticket.alert_ids.
            "alerts": [as_json(alert) for alert in alerts if alert is not None],
            "findings": findings_of(requests),
            "decisions": drain(readers.decisions.list, subject_type="ticket", subject_id=ticket_id),
            "evidence_requests": [as_json(request) for request in requests],
            "steps": [
                as_json(entry.step) for entry in readers.agent_log.list_for_ticket(ticket_id)
            ],
            # v2 L1: people do not review L1 verdicts (v1 box 16 dropped) and Incidents are L2.
            "reviews": [],
            "incident_ids": [],
        }

    @app.get("/api/alerts/{alert_id}")
    def get_alert(alert_id: str, readers: Readers):
        alert = readers.records.get_alert_record(alert_id)
        return not_found("alert") if alert is None else as_json(alert)

    @app.get("/api/alerts/{alert_id}/l1")
    def get_alert_l1(alert_id: str, readers: Readers):
        alert = readers.records.get_alert_record(alert_id)
        if alert is None:
            return not_found("alert")
        requests = readers.evidence_queue.list_by_requester("alert", alert_id)
        steps = readers.agent_log.list_for_subject("alert", alert_id)
        return {
            "alert": as_json(alert),
            "branch": as_json(readers.branches.get("alert", alert_id)),
            "decisions": drain(readers.decisions.list, subject_type="alert", subject_id=alert_id),
            "evidence_requests": [as_json(request) for request in requests],
            "steps": [as_json(entry.step) for entry in steps],
        }

    @app.get("/api/l1/decisions")
    def list_decisions(
        readers: Readers,
        subject_type: str | None = None,
        decision: str | None = None,
        reason: str | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_PAGE_LIMIT,
    ):
        result = readers.decisions.list(
            subject_type=subject_type,
            decision=decision,
            reason=reason,
            cursor=cursor,
            limit=limit,
        )
        return page(result.items, result.next_cursor)

    # ``from`` is a Python keyword, so the parameter needs the query alias.
    @app.get("/api/metrics")
    def get_metrics(from_: Annotated[int, Query(alias="from")], to: int):
        if from_ > to:
            return error("invalid_input", "from must not be later than to")
        # The stores the aggregate needs do not exist yet (C9, C15, Incident members),
        # so the window is echoed and available says there is nothing to count. Zeros
        # would read as "counted, none" instead (docs/api-contracts.md "지표").
        return {"from": from_, "to": to, "available": False}

    return app
