# 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, StrictStr, constr


class SiemAlert(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    kind: Literal["alert", "event"]
    scenario: StrictStr
    raw_ids: list[constr(pattern=r"^raw_", strict=True)]
    fields: dict[str, Any]
