# 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr

from . import evidence_schema


class TimelineEntry(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    time: StrictInt
    tactic: StrictStr | None
    technique: StrictStr | None
    description: StrictStr
    evidence: list[evidence_schema.Evidence] = Field(..., min_length=1)
