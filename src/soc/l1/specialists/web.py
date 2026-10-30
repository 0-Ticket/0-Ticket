"""Web specialist Agent (boxes 19, 31, C14, K16): one question about one Ticket, answered.

The flow is fixed by code, not by the model (D-008): read the Ticket, read its
stored alerts, read the HTTP flow of each source IP around them, then ask once.
Tools are reached only through the MCP server (15) under this agent's own
allowlist, so the agent that queued the request cannot widen what the specialist
may read.

What comes back is data, never a decision: the core owns ``ticket_id`` (it must
match the request's ``requester_id``), ``specialist``, ``question`` and
``created_at``, checks every cited evidence ID against the store, and falls back
to ``succeeded: unknown`` with ``confidence: 0`` when either fails
(docs/llm-policy.md 4, 6). Request paths and parameters are the attacker's
strings and stay data throughout (docs/security-policy.md 3).
"""

import json
import logging
import time
from collections.abc import Mapping, Sequence
from importlib.resources import files
from typing import Any

from soc.contracts import validate_contract
from soc.l1.llm_input import (
    Visible,
    fit_to_limit,
    flow_pool,
    flow_view,
    record_pool,
    summarize_alerts,
    ticket_view,
)
from soc.l1.mcp.internal import GET_ALERT
from soc.l1.mcp.web import QUERY_HTTP_FLOW
from soc.l1.specialists.base import NoStoredEvidenceError, Specialist, SpecialistContext
from soc.l1.tickets import TicketNotFoundError
from soc.llm import CallContext, call_llm

logger = logging.getLogger(__name__)

WEB_DOMAIN = "web"
# One name for this agent: its MCP allowlist key, its [llm.agents] key and C8 agent.
WEB_AGENT = "web_specialist"
PROMPT = files("soc.l1.prompts").joinpath("web_specialist.md")

IP_ENTITY = "ip"
EXCERPT_LIMIT = 2000
MINUTE_MS = 60_000

# Fallback reasons. Fixed phrases: a reason must never repeat model or log text.
LLM_OUTPUT_INVALID = "The model's answer did not satisfy the SpecialistFinding contract."
EVIDENCE_NOT_STORED = "The answer cited evidence that is not stored."
INPUT_TOO_LARGE = "The evidence did not fit the configured LLM input limit."
FALLBACK_SUMMARY = "The Web specialist could not produce a checked finding for this question."
FALLBACK_NOTE = "Alert of the Ticket this question is about"

# The Ticket fields the specialist shows the model. Its verdict is not one of
# them: that is what L1 is deciding with this answer.
TICKET_VIEW = ("ticket_id", "handling_type", "priority", "entities")


def _now_ms() -> int:
    return time.time_ns() // 1_000_000


def web_specialist(context: SpecialistContext) -> Specialist:
    """Build the Web specialist (registered for domain ``web``)."""

    def analyze(request: Mapping[str, Any]) -> dict[str, Any]:
        ticket_id = request["requester_id"]
        question = request["params"]["question"]
        ticket = context.tickets.get(ticket_id)
        if ticket is None:
            raise TicketNotFoundError("Ticket of this evidence request is not stored")

        step = _next_step(context, ticket_id)
        alerts = []
        for alert_id in dict.fromkeys(ticket["alert_ids"]):
            alert = _tool(context, ticket_id, step, GET_ALERT, alert_id=alert_id)
            step += 1
            if alert is not None:
                alerts.append(alert)
        if not alerts:
            # Every C14 needs at least one evidence item, and only stored records
            # can be cited. The queue fails the request and holds the Ticket (D-034).
            raise NoStoredEvidenceError("No alert of this Ticket is stored")

        flows = []
        for source in _sources(ticket, alerts):
            flows.append(flow_view(source, _flow(context, ticket_id, step, source, alerts)))
            step += 1

        data, visible = _llm_input(context, question, ticket, alerts, flows)
        if data is None:
            # docs/llm-policy.md 5: an input over the limit is not sent.
            logger.warning("Web specialist input exceeds l1.max_input_chars; not sent")
            answer = _fallback(alerts, INPUT_TOO_LARGE)
        else:
            result = call_llm(
                prompt_path=PROMPT,
                data=data,
                contract_name="SpecialistFinding",
                context=CallContext(
                    subject_type="ticket", subject_id=ticket_id, step=step, agent=WEB_AGENT
                ),
                record_step=context.agent_log,
                settings=context.settings.llm,
                provider_registry=context.providers,
                environ=context.environ,
            )
            step += 1
            answer = _answer(context, result, alerts, visible)

        finding = validate_contract(
            "SpecialistFinding",
            answer
            | {
                "ticket_id": ticket_id,
                "specialist": WEB_DOMAIN,
                "question": question,
                "created_at": _now_ms(),
            },
        ).model_dump(mode="json")
        _record(context, ticket_id, step, action="decision", input_text=question, output=finding)
        return finding

    return analyze


def _llm_input(
    context: SpecialistContext,
    question: str,
    ticket: Mapping[str, Any],
    alerts: Sequence[Mapping[str, Any]],
    flows: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, Visible]:
    """The input inside ``l1.max_input_chars`` (#91), or None, and the IDs it shows.

    Flow rows are dropped first (4xx, other non-2xx, then 2xx; farthest from the
    alerts first in each), then alerts down to one.
    """
    l1 = context.settings.l1
    at = [alert["time"] for alert in alerts]
    data: dict[str, Any] = {
        "question": question,
        "ticket": ticket_view(ticket, TICKET_VIEW),
        "alerts": summarize_alerts(
            alerts, top_rules=l1.summary_top_rules, max_records=l1.summary_records, at=at
        ),
        "flows": flows,
    }
    rows = flow_pool(at)
    for flow in flows:
        rows.add(flow["rows"], flow)
    own = record_pool(at, keep=1)
    own.add(data["alerts"]["records"], data["alerts"])
    visible = Visible()
    if not fit_to_limit(PROMPT, data, l1.max_input_chars, [rows, own]):
        return None, visible
    visible.add_summary(data["alerts"])
    for flow in flows:
        visible.add_flow(flow)
    return data, visible


def _answer(
    context: SpecialistContext,
    result: Any,
    alerts: Sequence[Mapping[str, Any]],
    visible: Visible,
) -> dict[str, Any]:
    """The model's finding if it holds up, otherwise the policy's fallback."""
    if not result.ok:
        logger.warning("Web specialist LLM call failed: %s", result.failure.rule)
        return _fallback(alerts, LLM_OUTPUT_INVALID)
    finding = result.value.model_dump(mode="json")
    if not _evidence_is_stored(context, finding["evidence"], visible):
        return _fallback(alerts, EVIDENCE_NOT_STORED)
    return finding


def _fallback(alerts: Sequence[Mapping[str, Any]], reason: str) -> dict[str, Any]:
    """C14 with nothing claimed: L1 does not use this as a ground for its verdict."""
    return {
        "summary": FALLBACK_SUMMARY,
        "attack_type": None,
        "succeeded": "unknown",
        "confidence": 0.0,
        "evidence": [
            {"ref_type": "alert", "ref_id": alert["alert_id"], "note": FALLBACK_NOTE}
            for alert in alerts
        ],
        "details": {},
        "needs_human": True,
        "human_reason": reason,
    }


def _evidence_is_stored(
    context: SpecialistContext, evidence: Sequence[Mapping[str, Any]], visible: Visible
) -> bool:
    """Every cited ID must have been shown to the model and exist (docs/llm-policy.md 4, #91).

    Alerts and events are looked up in the store. A raw record lives in the
    external SIEM (boxes 1, 2), so it counts as found when it is one of the
    ``raw_ids`` of an alert in the input.
    """
    store = context.records()
    for item in evidence:
        ref_type, ref_id = item["ref_type"], item["ref_id"]
        if not visible.allows(ref_type, ref_id):
            pass
        elif ref_type == "alert" and store.get_alert_record(ref_id) is not None:
            continue
        elif ref_type == "event" and store.get_event_record(ref_id) is not None:
            continue
        elif ref_type == "raw":
            continue
        # The ID itself is model output and may repeat log text: log the type only.
        logger.warning("Web specialist cited a %r reference that is not stored", ref_type)
        return False
    return True


def _sources(ticket: Mapping[str, Any], alerts: Sequence[Mapping[str, Any]]) -> tuple[str, ...]:
    """The source IPs to read a flow for: the Ticket's IP entities, then the alerts'."""
    values = [entity["value"] for entity in ticket["entities"] if entity["type"] == IP_ENTITY]
    values.extend(alert["src_ip"] for alert in alerts if alert["src_ip"])
    return tuple(dict.fromkeys(values))


def _flow(
    context: SpecialistContext,
    ticket_id: str,
    step: int,
    source: str,
    alerts: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """One source's HTTP requests around the alerts, inside the configured window."""
    specialist = context.settings.specialist
    window = specialist.flow_window_minutes * MINUTE_MS
    times = [alert["time"] for alert in alerts]
    return _tool(
        context,
        ticket_id,
        step,
        QUERY_HTTP_FLOW,
        src_ip=source,
        time_from=min(times) - window,
        time_to=max(times) + window,
        # The tool server refuses a limit above the query limit, so stay inside it.
        limit=min(specialist.flow_limit, context.settings.mcp.max_query_limit),
    )


def _tool(context: SpecialistContext, ticket_id: str, step: int, tool: str, **arguments: Any):
    """Call one tool under this agent's allowlist and log the step either way."""
    started = time.perf_counter()
    try:
        result = context.tools.call(WEB_AGENT, tool, **arguments)
    except Exception as error:
        # The type name only: a message can repeat log text (docs/security-policy.md 3).
        _record(
            context,
            ticket_id,
            step,
            action="tool_call",
            tool=tool,
            input_text=arguments,
            output=type(error).__name__,
            started=started,
        )
        raise
    _record(
        context,
        ticket_id,
        step,
        action="tool_call",
        tool=tool,
        input_text=arguments,
        output=result,
        started=started,
    )
    return result


def _record(
    context: SpecialistContext,
    ticket_id: str,
    step: int,
    *,
    action: str,
    input_text: object,
    output: object,
    tool: str | None = None,
    started: float | None = None,
) -> None:
    """Write one C8 step for this Ticket (Agent Log). ``output`` goes through the log service."""
    elapsed = 0 if started is None else max(0, int((time.perf_counter() - started) * 1000))
    context.agent_log.record(
        {
            "subject_type": "ticket",
            "subject_id": ticket_id,
            "step": step,
            "agent": WEB_AGENT,
            "action": action,
            "tool": tool,
            "prompt_version": None,
            "input_excerpt": _excerpt(input_text),
            "output_excerpt": "",
            "model": None,
            "tokens": None,
            "latency_ms": elapsed,
            "created_at": _now_ms(),
        },
        full_result=output,
    )


def _excerpt(value: object) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    return text[:EXCERPT_LIMIT]


def _next_step(context: SpecialistContext, ticket_id: str) -> int:
    """Start after the steps already logged for this Ticket: C8 numbers them once."""
    logged = context.agent_log.list_for_subject("ticket", ticket_id)
    return max((entry.step.step for entry in logged), default=0) + 1
