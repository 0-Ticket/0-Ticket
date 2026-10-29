# 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, StrictBool, StrictStr, constr


class UserInfo(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    user: StrictStr
    dept: StrictStr | None
    privileged: StrictBool
    extensions: dict[constr(pattern=r"^[^.]+\..+$", strict=True), Any]
