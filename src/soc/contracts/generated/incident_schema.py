# 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr, conint, constr

from . import incident_member_schema


class Incident(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    incident_id: constr(pattern=r"^in_", strict=True)
    title: StrictStr
    status: Literal["open", "investigating", "closed_benign", "escalated_to_case"]
    created_by: Literal["correlation", "manual"]
    severity_id: conint(ge=0, le=6, strict=True)
    first_seen: StrictInt
    last_seen: StrictInt
    tactics: list[StrictStr]
    summary: StrictStr | None
    members: list[incident_member_schema.IncidentMember]
    extensions: dict[constr(pattern=r"^[^.]+\..+$", strict=True), Any]
