# 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py

from __future__ import annotations

from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    confloat,
    constr,
)

from . import evidence_schema


class SpecialistFinding(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    ticket_id: constr(pattern=r"^tk_", strict=True)
    specialist: StrictStr
    question: StrictStr
    summary: StrictStr
    attack_type: StrictStr | None
    succeeded: Literal["yes", "no", "unknown"]
    confidence: confloat(ge=0.0, le=1.0, strict=True)
    evidence: list[evidence_schema.Evidence] = Field(..., min_length=1)
    details: dict[str, Any]
    needs_human: StrictBool
    human_reason: StrictStr | None
    created_at: StrictInt
