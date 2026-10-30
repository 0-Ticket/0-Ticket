"""L1 Ticket triage runtime (boxes 19-22, C6/C22/C14 -> C7/C23)."""

import json
import logging
import os
import re
import time
import uuid
from collections.abc import Callable, Mapping
from importlib.resources import files
from typing import Any

from soc.config import Settings
from soc.contracts import L1DecisionRecord, validate_contract
from soc.l1.agent_log import AgentLogService
from soc.l1.evidence.service import EvidenceQueueService
from soc.l1.llm_input import (
    Visible,
    cut,
    evidence_request_view,
    fit_to_limit,
    record_pool,
    similar_ticket_view,
    summarize_alerts,
    ticket_view,
)
from soc.l1.tickets import (
    DECIDED_TICKET_STATUSES,
    ConcurrentTicketUpdateError,
    InvalidTicketTransition,
    TicketNotFoundError,
    TicketService,
)
from soc.llm import CallContext, LLMCallResult, call_llm
from soc.plugins import PluginRegistry
from soc.store.paging import DEFAULT_PAGE_LIMIT, check_page_limit

logger = logging.getLogger(__name__)

AGENT = "l1"
TICKET_ORIGINS = ("l1_escalated", "scenario")
PROMPT = files("soc.l1.prompts").joinpath("l1_ticket_triage.md")
MINUTE_MS = 60_000
EXCERPT_LIMIT = 2_000
# The Ticket fields shown to the model; its alert list is shown as a summary.
TICKET_FIELDS = (
    "ticket_id",
    "origin",
    "status",
    "handling_type",
    "specialist",
    "priority",
    "entities",
)
_SPECIALIST_QUESTION = re.compile(r"^Specialist question:\s*(.+)$", re.MULTILINE)


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def _new_decision_id() -> str:
    return f"ld_{uuid.uuid4().hex}"


def _json(value: object) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), default=str)
    except (TypeError, ValueError):
        return "{}"


class L1TicketTriage:
    """Process new L1 and scenario Tickets through the evidence queue and C7."""

    def __init__(
        self,
        *,
        settings: Settings,
        tickets: TicketService,
        ticket_reader: TicketService,
        records: Any,
        evidence: EvidenceQueueService,
        decisions: Any,
        vector_tickets: Any,
        agent_log: AgentLogService,
        llm_call: Callable[..., LLMCallResult] = call_llm,
        provider_registry: PluginRegistry | None = None,
        environ: Mapping[str, str] | None = None,
        clock: Callable[[], int] = _now_ms,
        id_factory: Callable[[], str] = _new_decision_id,
    ):
        self.settings = settings
        self.tickets = tickets
        self.ticket_reader = ticket_reader
        self.records = records
        self.evidence = evidence
        self.decisions = decisions
        self.vector_tickets = vector_tickets
        self.agent_log = agent_log
        self.llm_call = llm_call
        self.provider_registry = provider_registry
        self.environ = os.environ if environ is None else environ
        self.clock = clock
        self.id_factory = id_factory

    def run(self, *, all_tickets: bool = False, limit: int = DEFAULT_PAGE_LIMIT) -> int:
        """Triage one page or every page of new L1 and scenario Tickets."""
        check_page_limit(limit)
        processed = 0
        for origin in TICKET_ORIGINS:
            cursor = None
            while True:
                page = self.ticket_reader.list(
                    status="new", origin=origin, cursor=cursor, limit=limit
                )
                if not page.items:
                    break
                for ticket in page.items:
                    if self._process_ticket(ticket["ticket_id"]):
                        processed += 1
                if not all_tickets or page.next_cursor is None:
                    break
                cursor = page.next_cursor
        return processed

    def _process_ticket(self, ticket_id: str) -> bool:
        try:
            triaging = self.tickets.transition(ticket_id, "triaging")
        except (ConcurrentTicketUpdateError, InvalidTicketTransition, TicketNotFoundError):
            logger.info("L1 Ticket changed before triage; skipping")
            return False
        self._record_step(
            ticket_id,
            action="decision",
            tool=None,
            input_value={"status": "new"},
            output_value={"status": triaging["status"]},
        )

        alerts = []
        for alert_id in dict.fromkeys(triaging["alert_ids"]):
            try:
                alert = self.records.get_alert_record(alert_id)
            except Exception as error:
                logger.warning("L1 Ticket alert read failed (%s)", type(error).__name__)
                self._hold(ticket_id, "evidence_request_failure", None)
                return True
            if alert is None:
                self._record_step(
                    ticket_id,
                    action="tool_call",
                    tool="ticket_alerts",
                    input_value={"alert_count": len(triaging["alert_ids"])},
                    output_value={"missing_alert": True},
                )
                self._hold(ticket_id, "evidence_request_failure", None)
                return True
            alerts.append(alert.model_dump(mode="json"))

        requests, finding, failed = self._collect_evidence(triaging, alerts)
        self._record_step(
            ticket_id,
            action="tool_call",
            tool="evidence_queue",
            input_value={"origin": triaging["origin"], "entity_count": len(triaging["entities"])},
            output_value={
                "request_types": [request["request_type"] for request in requests],
                "statuses": [request["status"] for request in requests],
                "finding_available": finding is not None,
            },
        )
        if failed:
            self._hold(ticket_id, "evidence_request_failure", None)
            return True

        similar_tickets = self._similar_tickets(triaging, ticket_id)
        try:
            data, visible = self._llm_input(triaging, alerts, requests, finding, similar_tickets)
        except Exception as error:
            logger.warning("L1 Ticket evidence summary failed (%s)", type(error).__name__)
            self._hold(ticket_id, "evidence_request_failure", None)
            return True
        if data is None:
            # docs/llm-policy.md 5: an input over the limit is not sent (D-036 budget).
            logger.warning("L1 Ticket triage input exceeds l1.max_input_chars; not sent")
            self._record_step(
                ticket_id,
                action="tool_call",
                tool="llm_input",
                input_value={"max_input_chars": self.settings.l1.max_input_chars},
                output_value={"input_too_large": True},
            )
            self._hold(ticket_id, "llm_failure", None)
            return True
        step = self._next_step(ticket_id)
        try:
            result = self.llm_call(
                prompt_path=PROMPT,
                data=data,
                contract_name="Verdict",
                context=CallContext(
                    subject_type="ticket", subject_id=ticket_id, step=step, agent=AGENT
                ),
                record_step=self.agent_log,
                settings=self.settings.llm,
                provider_registry=self.provider_registry,
                environ=self.environ,
            )
        except Exception as error:
            logger.warning("L1 Ticket triage LLM call failed (%s)", type(error).__name__)
            self._hold(ticket_id, "llm_failure", None)
            return True

        if not isinstance(result, LLMCallResult) or not result.ok:
            rule = getattr(getattr(result, "failure", None), "rule", "invalid_result")
            logger.warning("L1 Ticket triage LLM call failed (%s)", rule)
            self._hold(ticket_id, "llm_failure", None)
            return True

        verdict = result.value.model_dump(mode="json")
        try:
            evidence_is_stored = self._evidence_is_shown(verdict["evidence"], visible)
        except Exception as error:
            logger.warning("L1 Verdict evidence check failed (%s)", type(error).__name__)
            self._hold(ticket_id, "llm_failure", None)
            return True
        if not evidence_is_stored:
            logger.warning("L1 Verdict cited evidence that is not stored")
            self._hold(ticket_id, "llm_failure", None)
            return True

        confidence = verdict["confidence"]
        if confidence >= self.settings.l1.confidence_threshold and verdict["verdict"] == "fp":
            status, decision, reason = "closed_fp", "closed_fp", None
        elif confidence >= self.settings.l1.confidence_threshold and verdict["verdict"] == "tp":
            status, decision, reason = "l2_escalated", "l2_escalated", None
        else:
            status, decision, reason = "on_hold", "held", "below_threshold"

        try:
            saved = self.tickets.decide(ticket_id, status, verdict)
        except (ConcurrentTicketUpdateError, InvalidTicketTransition, TicketNotFoundError):
            logger.info("L1 Ticket changed before verdict save; skipping")
            return True
        record = self._save_decision(ticket_id, decision, confidence, reason)
        self._record_step(
            ticket_id,
            action="decision",
            tool=None,
            input_value=verdict,
            output_value={"decision": record.model_dump(mode="json"), "ticket": saved},
        )
        if status in {"closed_fp", "l2_escalated"}:
            self._index_decided(ticket_id)
        return True

    def _collect_evidence(
        self, ticket: Mapping[str, Any], alerts: list[dict[str, Any]]
    ) -> tuple[list[dict[str, Any]], dict[str, Any] | None, bool]:
        ticket_id = ticket["ticket_id"]
        queued_ids: set[str] = set()
        enqueue_failed = False

        def enqueue(**kwargs):
            request = self.evidence.enqueue(
                agent=AGENT,
                requester_type="ticket",
                requester_id=ticket_id,
                **kwargs,
            )
            queued_ids.add(request["request_id"])

        try:
            if ticket["specialist"] != "none":
                enqueue(
                    request_type="specialist_agent",
                    domain=ticket["specialist"],
                    params={"question": self._specialist_question()},
                )
            else:
                if not alerts or not ticket["entities"]:
                    raise ValueError("ticket_context_missing")
                start = min(alert["first_seen"] for alert in alerts)
                end = max(alert["last_seen"] for alert in alerts)
                window = self.settings.l1.siem_window_minutes * MINUTE_MS
                lookup_at = end
                for entity in ticket["entities"]:
                    enqueue(
                        request_type="lookup",
                        params={"entity": entity, "at": lookup_at},
                    )
                    if entity["type"] in {"ip", "host"}:
                        enqueue(
                            request_type="siem_mcp",
                            params={
                                "entity": entity,
                                "kind": "alert",
                                "start_at": max(0, start - window),
                                "end_at": end + window,
                                "limit": self.settings.mcp.max_query_limit,
                            },
                        )
        except Exception as error:
            enqueue_failed = True
            logger.warning("L1 Ticket evidence enqueue failed (%s)", type(error).__name__)

        run_failed = False
        try:
            self.evidence.run_until_empty()
        except Exception as error:
            run_failed = True
            logger.warning("L1 Ticket evidence queue failed (%s)", type(error).__name__)
        try:
            requests = self.evidence.results_for("ticket", ticket_id)
        except Exception as error:
            logger.warning(
                "L1 Ticket evidence results could not be read (%s)", type(error).__name__
            )
            return [], None, True
        requests = [request for request in requests if request["request_id"] in queued_ids]
        failed = (
            enqueue_failed
            or run_failed
            or not queued_ids
            or len(requests) != len(queued_ids)
            or any(request["status"] != "completed" for request in requests)
        )
        finding = None
        if not failed and ticket["specialist"] != "none":
            finding = next(
                (
                    request["result"]["finding"]
                    for request in requests
                    if request["request_type"] == "specialist_agent"
                ),
                None,
            )
            failed = finding is None
        return requests, finding, failed

    def _similar_tickets(self, ticket: Mapping[str, Any], ticket_id: str) -> list[dict[str, Any]]:
        query = {"ticket_id": ticket_id, "k": self.settings.l1.similar_tickets}
        try:
            matches = self.vector_tickets.search_by_ticket(
                ticket, k=self.settings.l1.similar_tickets
            )
            similar = []
            for other_id, score in matches:
                other = self.ticket_reader.get(other_id)
                if other is not None and other["status"] in DECIDED_TICKET_STATUSES:
                    similar.append({"ticket": other, "score": score})
            self._record_step(
                ticket_id,
                action="tool_call",
                tool="vector_ticket_search",
                input_value=query,
                output_value={"count": len(similar)},
            )
            return similar
        except Exception as error:
            logger.warning("L1 similar-ticket search failed (%s)", type(error).__name__)
            self._record_step(
                ticket_id,
                action="tool_call",
                tool="vector_ticket_search",
                input_value=query,
                output_value={"failed": True},
            )
            return []

    def _llm_input(
        self,
        ticket: Mapping[str, Any],
        alerts: list[dict[str, Any]],
        requests: list[dict[str, Any]],
        finding: Mapping[str, Any] | None,
        similar_tickets: list[dict[str, Any]],
    ) -> tuple[dict[str, Any] | None, Visible]:
        """The summarized input inside ``l1.max_input_chars``, or None, and what it shows."""
        l1 = self.settings.l1
        at = [alert["time"] for alert in alerts]
        summary = {"top_rules": l1.summary_top_rules, "max_records": l1.summary_records, "at": at}
        data: dict[str, Any] = {
            "ticket": ticket_view(ticket, TICKET_FIELDS),
            "alerts": summarize_alerts(alerts, **summary),
            "evidence_requests": [
                evidence_request_view(request, self.records, **summary) for request in requests
            ],
            "finding": cut(finding),
            "similar_tickets": [similar_ticket_view(item) for item in similar_tickets],
            "confidence_threshold": l1.confidence_threshold,
        }
        # SIEM records go first; at least one of the Ticket's own alerts stays.
        siem = record_pool(at)
        for request in data["evidence_requests"]:
            if request["request_type"] == "siem_mcp" and isinstance(request["result"], dict):
                siem.add(request["result"]["records"], request["result"])
        own = record_pool(at, keep=1)
        own.add(data["alerts"]["records"], data["alerts"])
        visible = Visible()
        if not fit_to_limit(PROMPT, data, l1.max_input_chars, [siem, own]):
            return None, visible
        visible.add_summary(data["alerts"])
        for request in data["evidence_requests"]:
            visible.add_summary(request["result"])
        visible.add_finding(data["finding"])
        return data, visible

    def _evidence_is_shown(self, evidence: list[Mapping[str, Any]], visible: Visible) -> bool:
        """Every cited ID was in the input and, for alerts and events, is stored."""
        for reference in evidence:
            ref_type, ref_id = reference["ref_type"], reference["ref_id"]
            if not visible.allows(ref_type, ref_id):
                return False
            if ref_type == "alert" and self.records.get_alert_record(ref_id) is None:
                return False
            if ref_type == "event" and self.records.get_event_record(ref_id) is None:
                return False
        return True

    def _specialist_question(self) -> str:
        text = PROMPT.read_text(encoding="utf-8")
        match = _SPECIALIST_QUESTION.search(text)
        if match is None:
            raise ValueError("specialist_question_missing")
        return match.group(1).strip()

    def _hold(self, ticket_id: str, reason: str, confidence: float | None) -> None:
        current = self.tickets.get(ticket_id)
        if current is None:
            logger.warning("L1 Ticket disappeared before hold record could be saved")
            return
        if current["status"] == "triaging":
            try:
                self.tickets.transition(ticket_id, "on_hold")
            except (ConcurrentTicketUpdateError, InvalidTicketTransition, TicketNotFoundError):
                logger.info("L1 Ticket changed before hold transition; skipping")
                return
        elif current["status"] != "on_hold":
            logger.info("L1 Ticket is %s; leaving its status unchanged", current["status"])
            return

        record = self._save_decision(ticket_id, "held", confidence, reason)
        self._record_step(
            ticket_id,
            action="decision",
            tool=None,
            input_value={"reason": reason, "confidence": confidence},
            output_value=record.model_dump(mode="json"),
        )

    def _save_decision(
        self,
        ticket_id: str,
        decision: str,
        confidence: float | None,
        reason: str | None,
    ) -> L1DecisionRecord:
        record = validate_contract(
            "L1DecisionRecord",
            {
                "decision_id": self.id_factory(),
                "subject_type": "ticket",
                "subject_id": ticket_id,
                "decision": decision,
                "confidence": confidence,
                "reason": reason,
                "created_at": self.clock(),
            },
        )
        return self.decisions.save(record)

    def _index_decided(self, ticket_id: str) -> None:
        try:
            self.tickets.index_decided(ticket_id, self.vector_tickets)
        except Exception as error:
            logger.warning("L1 decided Ticket vector indexing failed (%s)", type(error).__name__)
            self._record_step(
                ticket_id,
                action="tool_call",
                tool="vector_ticket_index",
                input_value={"ticket_id": ticket_id},
                output_value={"failed": True},
            )
            return
        self._record_step(
            ticket_id,
            action="tool_call",
            tool="vector_ticket_index",
            input_value={"ticket_id": ticket_id},
            output_value={"indexed": True},
        )

    def _record_step(
        self,
        ticket_id: str,
        *,
        action: str,
        tool: str | None,
        input_value: object,
        output_value: object,
    ) -> None:
        step = validate_contract(
            "AgentStep",
            {
                "subject_type": "ticket",
                "subject_id": ticket_id,
                "step": self._next_step(ticket_id),
                "agent": AGENT,
                "action": action,
                "tool": tool,
                "prompt_version": None,
                "input_excerpt": _json(input_value)[:EXCERPT_LIMIT],
                "output_excerpt": _json(output_value)[:EXCERPT_LIMIT],
                "model": None,
                "tokens": None,
                "latency_ms": 0,
                "created_at": self.clock(),
            },
        )
        self.agent_log.record(step, full_result=output_value)

    def _next_step(self, ticket_id: str) -> int:
        entries = self.agent_log.list_for_subject("ticket", ticket_id)
        return 1 + max((entry.step.step for entry in entries), default=0)
