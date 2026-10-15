# 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, constr

from . import entity_schema, verdict_schema


class Ticket(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    ticket_id: constr(pattern=r"^tk_", strict=True)
    status: Literal["new", "triaging", "awaiting_human", "closed_benign", "closed_fp", "escalated"]
    handling_type: StrictStr
    specialist: StrictStr
    priority: StrictInt
    alert_ids: list[constr(pattern=r"^al_", strict=True)] = Field(..., min_length=1)
    entities: list[entity_schema.Entity]
    verdict: verdict_schema.Verdict | None
    extensions: dict[constr(pattern=r"^[^.]+\..+$", strict=True), Any]
    created_at: StrictInt
    updated_at: StrictInt
    awaiting_human_at: StrictInt | None
