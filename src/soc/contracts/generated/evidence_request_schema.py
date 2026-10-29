# 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr, conint, constr


class EvidenceRequest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    request_id: constr(pattern=r"^rq_", strict=True)
    requester_type: Literal["ticket", "incident", "alert"]
    requester_id: StrictStr
    request_type: Literal["specialist_agent", "siem_mcp", "lookup"]
    domain: StrictStr | None
    params: dict[str, Any]
    retry_count: conint(ge=0, strict=True)
    status: Literal["pending", "in_progress", "completed", "failed"]
    failure_reason: StrictStr | None
    result: dict[str, Any] | None
    created_at: StrictInt
    updated_at: StrictInt
