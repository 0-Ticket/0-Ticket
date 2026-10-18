# 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr, confloat, constr


class L1DecisionRecord(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    decision_id: constr(pattern=r"^ld_", strict=True)
    subject_type: Literal["alert", "ticket"]
    subject_id: StrictStr
    decision: Literal["l1_escalated", "held", "closed_fp", "l2_escalated"]
    confidence: confloat(ge=0.0, le=1.0, strict=True) | None
    reason: Literal["below_threshold", "llm_failure", "evidence_request_failure"] | None
    created_at: StrictInt
