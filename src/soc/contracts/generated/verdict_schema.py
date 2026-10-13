# 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, confloat

from . import evidence_schema


class Verdict(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    verdict: Literal["tp", "fp", "unknown"]
    confidence: confloat(ge=0.0, le=1.0, strict=True)
    summary: StrictStr
    evidence: list[evidence_schema.Evidence] = Field(..., min_length=1)
    recommended_action: StrictStr
    needs_human: StrictBool
    human_reason: StrictStr | None
