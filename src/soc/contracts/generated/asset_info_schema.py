# 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py

from __future__ import annotations

from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    StrictBool,
    StrictInt,
    StrictStr,
    conint,
    constr,
)


class AssetInfo(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    match: StrictStr
    hostname: StrictStr
    criticality: conint(ge=1, le=5, strict=True)
    owner: StrictStr | None
    zone: StrictStr | None
    shared: StrictBool
    valid_from: StrictInt | None
    valid_to: StrictInt | None
    extensions: dict[constr(pattern=r"^[^.]+\..+$", strict=True), Any]
