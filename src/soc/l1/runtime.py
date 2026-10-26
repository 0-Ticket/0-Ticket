"""L1 Alert entity lookup runtime (box 11, C21 -> C22 -> C23/C6)."""

import json
import logging
import os
import time
import uuid
from collections.abc import Callable, Mapping, Sequence
from importlib.resources import files
from typing import Any

from soc.config import Settings, load_config
from soc.contracts import AlertRecord, L1DecisionRecord, validate_contract
from soc.store import open_store
from soc.store.paging import DEFAULT_PAGE_LIMIT, check_page_limit
from soc.store.vectors.tickets import VectorTicketService

# Initialize store modules before importing L1 services to avoid the ticket
# store and ticket service importing each other while the store package loads.
# isort: split
from soc.l1.agent_log import AgentLogService
from soc.l1.entities import alert_entities
from soc.l1.evidence import open_evidence_queue
from soc.l1.evidence.handlers import default_handlers
from soc.l1.evidence.service import EvidenceQueueService
from soc.l1.llm_input import (
    Visible,
    alert_view,
    evidence_request_view,
    fit_to_limit,
    record_pool,
    similar_ticket_view,
)
from soc.l1.mcp import build_tool_server
from soc.l1.specialists import SpecialistContext
from soc.l1.ticket_triage import L1TicketTriage
from soc.l1.tickets import DECIDED_TICKET_STATUSES, TicketService
from soc.l1.vector_search import SearchUnavailableError, UnavailableTicketSearch
from soc.llm import CallContext, LLMCallResult, call_llm
from soc.normalize.lookup import open_lookup
from soc.plugins import PluginRegistry

logger = logging.getLogger(__name__)

AGENT = "l1"
BRANCH_PATH = "l1_entity_lookup"
TICKET_ORIGIN = "l1_escalated"
PROMPT = files("soc.l1.prompts").joinpath("l1_entity_lookup.md")
MINUTE_MS = 60_000
_EXCERPT_LIMIT = 2_000


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _new_decision_id() -> str:
    return f"ld_{uuid.uuid4().hex}"


def _json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return "{}"


class L1Runtime:
    """Process C21 L1 lookup branches using replaceable stores and services."""

    def __init__(
        self,
        *,
        settings: Settings,
        branches: Any,
        decisions: Any,
        decision_reader: Any,
        records: Any,
        tickets: TicketService,
        ticket_reader: TicketService,
        evidence: EvidenceQueueService,
        vector_tickets: Any,
        agent_log: AgentLogService,
        ticket_triage: L1TicketTriage | None = None,
        llm_call: Callable[..., LLMCallResult] = call_llm,
        provider_registry: PluginRegistry | None = None,
        environ: Mapping[str, str] | None = None,
        clock: Callable[[], int] = _now_ms,
        id_factory: Callable[[], str] = _new_decision_id,
        resources: Sequence[Any] = (),
    ):
        self.settings = settings
        self.branches = branches
        self.decisions = decisions
        self.decision_reader = decision_reader
        self.records = records
        self.tickets = tickets
        self.ticket_reader = ticket_reader
        self.evidence = evidence
        self.vector_tickets = vector_tickets
        self.agent_log = agent_log
        self.ticket_triage = ticket_triage
        self.llm_call = llm_call
        self.provider_registry = provider_registry
        self.environ = os.environ if environ is None else environ
        self.clock = clock
        self.id_factory = id_factory
        self._resources = tuple(resources)

    def run(self, *, all_alerts: bool = False, limit: int = DEFAULT_PAGE_LIMIT) -> int:
        """Process the first page, or every page with ``all_alerts=True``."""
        check_page_limit(limit)
        after_seq = 0
        processed = 0
        while True:
            page = self.branches.list_by_path(BRANCH_PATH, after_seq, limit)
            if not page:
                break
            for stored in page:
                after_seq = stored.seq
                branch = stored.record
                if branch.subject_type != "alert":
                    continue
                if self.decision_reader.get("alert", branch.subject_id) is not None:
                    continue
                self._process_alert(branch.subject_id)
                processed += 1
            if not all_alerts or len(page) < limit:
                break
        if self.ticket_triage is not None:
            processed += self.ticket_triage.run(all_tickets=all_alerts, limit=limit)
        return processed

    def close(self) -> None:
        """Close the resources opened by ``build_runtime``."""
        seen: set[int] = set()
        for resource in reversed(self._resources):
            if id(resource) in seen:
                continue
            seen.add(id(resource))
            close = getattr(resource, "close", None)
            if callable(close):
                close()

    def _process_alert(self, alert_id: str) -> None:
        alert = self.records.get_alert_record(alert_id)
        if alert is None:
            logger.warning("L1 branch has no stored AlertRecord")
            self._save_decision(alert_id, "held", None, "llm_failure", step=True)
            return

        entities = alert_entities(alert)
        if not entities:
            logger.warning("L1 AlertRecord has no lookup entities")
            self._save_decision(alert_id, "held", None, "llm_failure", step=True)
            return

        requests, evidence_failed = self._collect_evidence(alert, entities)
        self._record_step(
            alert_id,
            action="tool_call",
            tool="evidence_queue",
            input_value={"entity_count": len(entities)},
            output_value=requests,
        )
        if evidence_failed:
            self._save_decision(alert_id, "held", None, "evidence_request_failure", step=True)
            return

        similar_tickets = self._similar_tickets(alert, entities)
        try:
            data, visible = self._llm_input(alert, entities, requests, similar_tickets)
        except Exception as error:
            logger.warning("L1 evidence summary failed (%s)", type(error).__name__)
            self._save_decision(alert_id, "held", None, "evidence_request_failure", step=True)
            return
        if data is None:
            # docs/llm-policy.md 5: an input over the limit is not sent (D-036 budget).
            logger.warning("L1 LLM input exceeds l1.max_input_chars; not sent")
            self._record_step(
                alert_id,
                action="tool_call",
                tool="llm_input",
                input_value={"max_input_chars": self.settings.l1.max_input_chars},
                output_value={"input_too_large": True},
            )
            self._save_decision(alert_id, "held", None, "llm_failure", step=True)
            return
        step = self._next_step(alert_id)
        try:
            result = self.llm_call(
                prompt_path=PROMPT,
                data=data,
                contract_name="Verdict",
                context=CallContext(
                    subject_type="alert", subject_id=alert_id, step=step, agent=AGENT
                ),
                record_step=self.agent_log,
                settings=self.settings.llm,
                provider_registry=self.provider_registry,
                environ=self.environ,
            )
        except Exception as error:
            logger.warning("L1 LLM call failed (%s)", type(error).__name__)
            self._save_decision(alert_id, "held", None, "llm_failure", step=True)
            return

        if not isinstance(result, LLMCallResult) or not result.ok:
            rule = getattr(getattr(result, "failure", None), "rule", "invalid_result")
            logger.warning("L1 LLM call failed (%s)", rule)
            self._save_decision(alert_id, "held", None, "llm_failure", step=True)
            return

        verdict = result.value.model_dump(mode="json")
        if not self._evidence_is_shown(verdict["evidence"], visible):
            logger.warning("L1 Verdict cited evidence that is not stored")
            self._save_decision(alert_id, "held", None, "llm_failure", step=True)
            return

        confidence = verdict["confidence"]
        promoted_ticket = None
        if verdict["verdict"] == "tp" and confidence >= self.settings.l1.confidence_threshold:
            promoted_ticket = self._promote(alert, entities)
            decision = "l1_escalated"
            reason = None
        else:
            decision = "held"
            reason = "below_threshold"
        saved = self._save_decision(alert_id, decision, confidence, reason, step=False)
        self._record_step(
            alert_id,
            action="decision",
            tool=None,
            input_value=verdict,
            output_value={
                "decision": saved.model_dump(mode="json"),
                "ticket": promoted_ticket,
            },
        )

    def _collect_evidence(
        self, alert: AlertRecord, entities: Sequence[Mapping[str, str]]
    ) -> tuple[list[dict[str, Any]], bool]:
        alert_id = alert.alert_id
        expected_requests = len(entities) + sum(
            entity["type"] in {"ip", "host"} for entity in entities
        )
        enqueue_error = False
        try:
            for entity in entities:
                self.evidence.enqueue(
                    agent=AGENT,
                    requester_type="alert",
                    requester_id=alert_id,
                    request_type="lookup",
                    params={"entity": dict(entity), "at": alert.time},
                )
                if entity["type"] in {"ip", "host"}:
                    window_ms = self.settings.l1.siem_window_minutes * MINUTE_MS
                    self.evidence.enqueue(
                        agent=AGENT,
                        requester_type="alert",
                        requester_id=alert_id,
                        request_type="siem_mcp",
                        params={
                            "entity": dict(entity),
                            "kind": "alert",
                            "start_at": max(0, alert.time - window_ms),
                            "end_at": alert.time + window_ms,
                            "limit": self.settings.mcp.max_query_limit,
                        },
                    )
        except Exception as error:
            enqueue_error = True
            logger.warning("L1 evidence request enqueue failed (%s)", type(error).__name__)

        run_error = False
        try:
            self.evidence.run_until_empty()
        except Exception as error:
            run_error = True
            logger.warning("L1 evidence queue failed (%s)", type(error).__name__)
        try:
            requests = self.evidence.results_for("alert", alert_id)
        except Exception as error:
            logger.warning("L1 evidence results could not be read (%s)", type(error).__name__)
            return [], True
        failed = (
            enqueue_error
            or run_error
            or len(requests) < expected_requests
            or any(request.get("status") != "completed" for request in requests)
        )
        return requests, failed

    def _similar_tickets(
        self, alert: AlertRecord, entities: Sequence[Mapping[str, str]]
    ) -> list[dict[str, Any]]:
        query = {"entities": list(entities), "k": self.settings.l1.similar_tickets}
        try:
            matches = self.vector_tickets.search_by_entities(
                entities,
                "Related decided Tickets for this Alert.",
                k=self.settings.l1.similar_tickets,
            )
            tickets = []
            for ticket_id, score in matches:
                ticket = self.ticket_reader.get(ticket_id)
                if ticket is not None and ticket["status"] in DECIDED_TICKET_STATUSES:
                    tickets.append({"ticket": ticket, "score": score})
            self._record_step(
                alert.alert_id,
                action="tool_call",
                tool="vector_ticket_search",
                input_value=query,
                output_value={"count": len(tickets)},
            )
            return tickets
        except SearchUnavailableError:
            # #105: the search path is disabled for this process, not failing for this Alert.
            self._record_step(
                alert.alert_id,
                action="tool_call",
                tool="vector_ticket_search",
                input_value=query,
                output_value={"unavailable": True},
            )
            return []
        except Exception as error:
            logger.warning("L1 similar-ticket search failed (%s)", type(error).__name__)
            self._record_step(
                alert.alert_id,
                action="tool_call",
                tool="vector_ticket_search",
                input_value=query,
                output_value={"failed": True},
            )
            return []

    def _llm_input(
        self,
        alert: AlertRecord,
        entities: Sequence[Mapping[str, str]],
        requests: Sequence[Mapping[str, Any]],
        similar_tickets: Sequence[Mapping[str, Any]],
    ) -> tuple[dict[str, Any] | None, Visible]:
        """The summarized input inside ``l1.max_input_chars``, or None, and what it shows."""
        l1 = self.settings.l1
        at = [alert.time]
        data: dict[str, Any] = {
            "alert": alert_view(alert),
            "entities": list(entities),
            "representative_entity": entities[0],
            "evidence_requests": [
                evidence_request_view(
                    request,
                    self.records,
                    top_rules=l1.summary_top_rules,
                    max_records=l1.summary_records,
                    at=at,
                )
                for request in requests
            ],
            "similar_tickets": [similar_ticket_view(item) for item in similar_tickets],
        }
        pool = record_pool(at)
        for request in data["evidence_requests"]:
            if request["request_type"] == "siem_mcp" and isinstance(request["result"], dict):
                pool.add(request["result"]["records"], request["result"])
        visible = Visible()
        if not fit_to_limit(PROMPT, data, l1.max_input_chars, [pool]):
            return None, visible
        visible.add_records([data["alert"]])
        for request in data["evidence_requests"]:
            visible.add_summary(request["result"])
        return data, visible

    def _evidence_is_shown(self, evidence: Sequence[Mapping[str, Any]], visible: Visible) -> bool:
        """Every cited ID was in the input and, for alerts and events, is stored."""
        for reference in evidence:
            ref_type, ref_id = reference["ref_type"], reference["ref_id"]
            stored = visible.allows(ref_type, ref_id) and (
                (ref_type == "alert" and self.records.get_alert_record(ref_id) is not None)
                or (ref_type == "event" and self.records.get_event_record(ref_id) is not None)
                or ref_type == "raw"
            )
            if not stored:
                logger.warning("L1 Verdict cited a %r reference that was not shown", ref_type)
                return False
        return True

    def _promote(self, alert: AlertRecord, entities: Sequence[Mapping[str, str]]) -> dict[str, Any]:
        existing = self._ticket_for_alert(alert.alert_id)
        if existing is not None:
            return existing
        is_web = bool(alert.http_url)
        return self.tickets.create(
            alert.model_dump(mode="json"),
            origin=TICKET_ORIGIN,
            entities=entities,
            handling_type="web_attack" if is_web else "other",
            specialist="web" if is_web else "none",
        )

    def _ticket_for_alert(self, alert_id: str) -> dict[str, Any] | None:
        cursor = None
        while True:
            page = self.ticket_reader.list(
                status=None,
                origin=TICKET_ORIGIN,
                cursor=cursor,
                limit=DEFAULT_PAGE_LIMIT,
            )
            for ticket in page.items:
                if alert_id in ticket["alert_ids"]:
                    return ticket
            if page.next_cursor is None:
                return None
            cursor = page.next_cursor

    def _save_decision(
        self,
        alert_id: str,
        decision: str,
        confidence: float | None,
        reason: str | None,
        *,
        step: bool,
    ) -> L1DecisionRecord:
        record = validate_contract(
            "L1DecisionRecord",
            {
                "decision_id": self.id_factory(),
                "subject_type": "alert",
                "subject_id": alert_id,
                "decision": decision,
                "confidence": confidence,
                "reason": reason,
                "created_at": self.clock(),
            },
        )
        saved = self.decisions.save(record)
        if step:
            self._record_step(
                alert_id,
                action="decision",
                tool=None,
                input_value={"subject_type": "alert", "subject_id": alert_id},
                output_value=saved.model_dump(mode="json"),
            )
        return saved

    def _record_step(
        self,
        alert_id: str,
        *,
        action: str,
        tool: str | None,
        input_value: object,
        output_value: object,
    ) -> None:
        step = validate_contract(
            "AgentStep",
            {
                "subject_type": "alert",
                "subject_id": alert_id,
                "step": self._next_step(alert_id),
                "agent": AGENT,
                "action": action,
                "tool": tool,
                "prompt_version": None,
                "input_excerpt": _json(input_value)[:_EXCERPT_LIMIT],
                "output_excerpt": _json(output_value)[:_EXCERPT_LIMIT],
                "model": None,
                "tokens": None,
                "latency_ms": 0,
                "created_at": self.clock(),
            },
        )
        self.agent_log.record(step, full_result=output_value)

    def _next_step(self, alert_id: str) -> int:
        entries = self.agent_log.list_for_subject("alert", alert_id)
        return 1 + max((entry.step.step for entry in entries), default=0)


def build_runtime(
    settings: Settings | None = None,
    environ: Mapping[str, str] | None = None,
    *,
    store_registry: PluginRegistry | None = None,
    lookup_registry: PluginRegistry | None = None,
    evidence_registry: PluginRegistry | None = None,
    siem_registry: PluginRegistry | None = None,
    mcp_servers: PluginRegistry | None = None,
    vector_registry: PluginRegistry | None = None,
    embedder_registry: PluginRegistry | None = None,
    provider_registry: PluginRegistry | None = None,
    tool_server_factory: Callable[..., Any] = build_tool_server,
    lookup_factory: Callable[..., Any] = open_lookup,
    evidence_queue_factory: Callable[..., Any] = open_evidence_queue,
    vector_ticket_factory: Callable[..., Any] = VectorTicketService.from_settings,
    llm_call: Callable[..., LLMCallResult] = call_llm,
) -> L1Runtime:
    """Assemble L1 services and stores from the selected backend settings."""
    env = os.environ if environ is None else environ
    settings = load_config(environ=env) if settings is None else settings
    resources: list[Any] = []

    def store(kind: str):
        opened = open_store(kind, settings, env, store_registry)
        resources.append(opened)
        return opened

    try:
        tickets = TicketService(store("tickets"))
        ticket_reader = TicketService(store("readonly_tickets"))
        agent_log = AgentLogService.from_settings(settings, env, store_registry)
        resources.append(agent_log)

        tools = tool_server_factory(settings, env, siem_registry, mcp_servers)
        lookup = lookup_factory(settings, env, lookup_registry)
        resources.append(lookup)
        records = store("readonly_records")
        context = SpecialistContext(
            settings,
            env,
            tools,
            tickets,
            lambda: records,
            agent_log,
            provider_registry,
        )
        queue = evidence_queue_factory(settings, env, evidence_registry)
        resources.append(queue)
        evidence = EvidenceQueueService(
            queue,
            mcp=settings.mcp,
            max_retries=settings.evidence_queue.max_retries,
            handlers=default_handlers(context, lookup),
            tickets=tickets,
        )
        # #105: a search dependency that cannot be opened disables the search path only.
        # Every other service here still stops startup through the outer handler below.
        try:
            vector_tickets = vector_ticket_factory(
                settings,
                vector_registry=vector_registry,
                embedder_registry=embedder_registry,
            )
        except Exception as error:
            logger.warning(
                "L1 similar-Ticket search is unavailable; starting without it (%s)",
                type(error).__name__,
            )
            vector_tickets = UnavailableTicketSearch()
        resources.append(vector_tickets)
        branches = store("readonly_branches")
        decisions = store("l1_decisions")
        decision_reader = store("readonly_l1_decisions")
        ticket_triage = L1TicketTriage(
            settings=settings,
            tickets=tickets,
            ticket_reader=ticket_reader,
            records=records,
            evidence=evidence,
            decisions=decisions,
            vector_tickets=vector_tickets,
            agent_log=agent_log,
            llm_call=llm_call,
            provider_registry=provider_registry,
            environ=env,
        )
        return L1Runtime(
            settings=settings,
            branches=branches,
            decisions=decisions,
            decision_reader=decision_reader,
            records=records,
            tickets=tickets,
            ticket_reader=ticket_reader,
            evidence=evidence,
            vector_tickets=vector_tickets,
            agent_log=agent_log,
            ticket_triage=ticket_triage,
            llm_call=llm_call,
            provider_registry=provider_registry,
            environ=env,
            resources=resources,
        )
    except Exception:
        for resource in reversed(resources):
            close = getattr(resource, "close", None)
            if callable(close):
                close()
        raise
