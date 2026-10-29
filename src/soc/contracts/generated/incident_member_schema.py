# 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr, constr

from . import entity_schema


class IncidentMember(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    member_type: Literal["ticket", "hunt"]
    ticket_id: constr(pattern=r"^tk_", strict=True) | None
    hunt_id: constr(pattern=r"^ht_", strict=True) | None
    source: Literal["l1", "human_l1", "l3"]
    rule: StrictStr
    matched_entity: entity_schema.Entity | None
    excluded: StrictBool
    excluded_reason: StrictStr | None
