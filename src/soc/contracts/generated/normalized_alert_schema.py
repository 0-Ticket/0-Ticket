# 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr, conint, constr


class NormalizedAlert(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    class_uid: Literal[2004]
    time: StrictInt
    severity_id: conint(ge=0, le=6, strict=True)
    rule_id: StrictStr
    rule_name: StrictStr
    src_ip: StrictStr | None
    src_port: StrictInt | None
    dst_ip: StrictStr | None
    dst_port: StrictInt | None
    host: StrictStr | None
    user: StrictStr | None
    http_url: StrictStr | None
    http_status: StrictInt | None
    techniques: list[StrictStr]
    raw_ids: list[constr(pattern=r"^raw_", strict=True)]
    unmapped: dict[str, Any]
    extensions: dict[constr(pattern=r"^[^.]+\..+$", strict=True), Any]
