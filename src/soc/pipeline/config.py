"""[pipeline] 설정 읽기와 파이프용 [executor] 설정 만들기(#316)."""

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

NORMALIZE_WORKER = "soc.pipeline.workers:build_normalize_worker"
TICKETING_WORKER = "soc.pipeline.workers:build_ticketing_worker"


class PipelineConfigError(Exception):
    """[pipeline] 설정이 없거나 값이 틀렸다. 메시지에는 키 이름만 담는다."""


@dataclass(frozen=True)
class PipelineSettings:
    normalize_interval_seconds: float
    ticketing_interval_seconds: float
    shutdown_timeout_seconds: float


def read_pipeline(config: Mapping[str, Any]) -> PipelineSettings:
    section = config.get("pipeline")
    if not isinstance(section, Mapping):
        raise PipelineConfigError("[pipeline] 설정이 없다")
    values = []
    for key in (
        "normalize_interval_seconds",
        "ticketing_interval_seconds",
        "shutdown_timeout_seconds",
    ):
        value = section.get(key)
        if type(value) not in (int, float) or value <= 0:
            raise PipelineConfigError(f"[pipeline] {key}는 0보다 큰 수다")
        values.append(float(value))
    return PipelineSettings(*values)


def build_executor_config(config: Mapping[str, Any]) -> dict[str, Any]:
    """파이프가 돌릴 설정. 정규화·Ticket 단계를 켜고 L3는 끈다. 입력은 바꾸지 않는다."""
    settings = read_pipeline(config)
    built = copy.deepcopy(dict(config))
    executor = built.setdefault("executor", {})
    executor["shutdown_timeout_seconds"] = settings.shutdown_timeout_seconds
    executor["normalize"] = {
        "interval_seconds": settings.normalize_interval_seconds,
        "poll_limit": 1,
        "workers": [NORMALIZE_WORKER],
    }
    executor["ticketing"] = {
        "interval_seconds": settings.ticketing_interval_seconds,
        "poll_limit": 1,
        "workers": [TICKETING_WORKER],
    }
    l3 = executor.setdefault("l3", {"poll_limit": 1, "workers": []})
    l3["interval_seconds"] = 0
    return built
