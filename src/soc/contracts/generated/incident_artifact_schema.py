# 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, StrictStr, constr

from . import ioc_schema, recommendation_schema, timeline_entry_schema


class IncidentArtifact(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    incident_id: constr(pattern=r"^in_", strict=True)
    timeline: list[timeline_entry_schema.TimelineEntry]
    affected_assets: list[StrictStr]
    iocs: list[ioc_schema.Ioc]
    suspected_cause: StrictStr
    recommendations: list[recommendation_schema.Recommendation]
    needs_human: StrictBool
    human_reason: StrictStr | None
    generated_at: StrictInt
