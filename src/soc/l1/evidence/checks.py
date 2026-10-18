"""C22 core checks the Schema cannot express (docs/data-contracts.md C22 "코어 검증").

Both functions validate the C22 Schema first and return the validated dict.
Error messages name the broken rule only, never a request value: values can
come from logs an attacker wrote (docs/security-policy.md 3).
"""

from collections.abc import Mapping
from typing import Any

from soc.config import McpSettings
from soc.contracts import validate_contract

from .base import EvidenceRequestRejected

# Incident requests belong to L2, which is not built yet (#53 scope).
SUPPORTED_REQUESTERS = frozenset({"alert", "ticket"})


def _validated(request: Mapping[str, Any]) -> dict[str, Any]:
    return validate_contract("EvidenceRequest", dict(request)).model_dump(mode="json")


def check_request(request: Mapping[str, Any], mcp: McpSettings) -> dict[str, Any]:
    """The checks run before a request is stored."""
    validated = _validated(request)
    if validated["requester_type"] not in SUPPORTED_REQUESTERS:
        raise EvidenceRequestRejected("requester_type incident is not queued yet")
    if validated["request_type"] == "siem_mcp":
        params = validated["params"]
        if params["end_at"] < params["start_at"]:
            raise EvidenceRequestRejected("params.end_at is before params.start_at")
        if params["limit"] > mcp.max_query_limit:
            raise EvidenceRequestRejected("params.limit is above mcp.max_query_limit")
    return validated


def check_result(request: Mapping[str, Any]) -> dict[str, Any]:
    """The checks run before a completed request is stored."""
    validated = _validated(request)
    if validated["status"] == "completed" and validated["request_type"] == "specialist_agent":
        if validated["result"]["finding"]["ticket_id"] != validated["requester_id"]:
            raise EvidenceRequestRejected("result.finding.ticket_id is not requester_id")
    return validated
