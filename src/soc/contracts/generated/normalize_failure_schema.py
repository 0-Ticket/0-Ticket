# 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr, constr


class NormalizeFailure(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    mapping_profile: constr(min_length=1, strict=True)
    raw_ids: list[constr(pattern=r"^raw_", strict=True)]
    reason: Literal["unknown_scenario", "unknown_mapping_profile", "missing_required", "bad_value"]
    missing_fields: list[StrictStr]
    detail: StrictStr | None
    failed_at: StrictInt
