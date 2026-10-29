# 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, StrictBool, StrictInt, StrictStr, constr

from . import backtest_schema


class RuleProposal(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    proposal_id: constr(pattern=r"^rp_", strict=True)
    hunt_id: constr(pattern=r"^ht_", strict=True) | None
    case_id: constr(pattern=r"^cs_", strict=True) | None
    title: StrictStr
    techniques: list[StrictStr]
    sigma_rule: StrictStr
    siem_query: StrictStr | None
    syntax_ok: StrictBool
    backtest: backtest_schema.Backtest | None
    status: Literal["draft", "approved", "rejected", "deployed"]
    reviewer: StrictStr | None
    needs_human: StrictBool
    human_reason: StrictStr | None
    created_at: StrictInt
