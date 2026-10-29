# 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py

from __future__ import annotations

from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    StrictBool,
    StrictInt,
    StrictStr,
    conint,
    constr,
)

from . import evidence_schema


class HuntFinding(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    hunt_id: constr(pattern=r"^ht_", strict=True)
    hypothesis: StrictStr
    techniques: list[StrictStr]
    method: Literal["baseline", "hypothesis"]
    query_summary: StrictStr
    evidence: list[evidence_schema.Evidence]
    is_anomaly: StrictBool
    severity_id: conint(ge=0, le=6, strict=True)
    incident_id: constr(pattern=r"^in_", strict=True) | None
    rule_candidate: StrictBool
    needs_human: StrictBool
    human_reason: StrictStr | None
    created_at: StrictInt
