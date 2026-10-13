# 자동 생성, 직접 수정 금지. Regenerate: uv run python scripts/generate_contracts.py

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, StrictInt


class Backtest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    window_start_at: StrictInt
    window_end_at: StrictInt
    attack_hits: StrictInt
    benign_hits: StrictInt
