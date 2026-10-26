# 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, StrictInt, StrictStr, conint, constr

from . import asset_info_schema, user_info_schema


class EventRecord(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    event_id: constr(pattern=r"^ev_", strict=True)
    source_record_id: constr(pattern=r"^src_", strict=True)
    class_uid: StrictInt
    time: StrictInt
    activity: StrictStr
    src_ip: StrictStr | None
    dst_ip: StrictStr | None
    host: StrictStr | None
    user: StrictStr | None
    http_url: StrictStr | None
    http_status: StrictInt | None
    http_bytes: conint(ge=0, strict=True) | None
    api_operation: StrictStr | None
    status: StrictStr | None
    src_asset: asset_info_schema.AssetInfo | None
    dst_asset: asset_info_schema.AssetInfo | None
    user_info: user_info_schema.UserInfo | None
    raw_ids: list[constr(pattern=r"^raw_", strict=True)]
    unmapped: dict[str, Any]
    extensions: dict[constr(pattern=r"^[^.]+\..+$", strict=True), Any]
