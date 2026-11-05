"""[l3.hunt] 설정 읽기. 틀리면 ConfigError."""

from dataclasses import dataclass
from typing import Any


class ConfigError(Exception):
    """[l3.hunt] 설정이 틀렸다."""


@dataclass(frozen=True)
class HuntSettings:
    collect_before: bool
    news_window_days: float
    news_limit: int
    case_limit: int
    max_hypotheses: int
    lookback_days: float
    confirm_threshold: float
    max_attempts: int
    # [l3.intel.attack] version. attack_techniques는 버전마다 쌓이므로 이 버전으로 고른다(#221)
    attack_version: str


def _number(table: dict[str, Any], key: str) -> float:
    value = table.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ConfigError(f"l3.hunt.{key}는 수여야 한다")
    return value


def _positive(table: dict[str, Any], key: str) -> float:
    value = _number(table, key)
    if value <= 0:
        raise ConfigError(f"l3.hunt.{key}는 0보다 커야 한다")
    return value


def _count(table: dict[str, Any], key: str, *, minimum: int) -> int:
    value = table.get(key)
    if type(value) is not int or value < minimum:
        raise ConfigError(f"l3.hunt.{key}는 {minimum} 이상의 정수여야 한다")
    return value


def read_hunt_settings(l3: dict[str, Any]) -> HuntSettings:
    """load_config()["l3"]에서 [l3.hunt]와 [l3.intel.attack] version을 읽는다."""
    hunt = l3.get("hunt")
    if not isinstance(hunt, dict):
        raise ConfigError("l3.hunt가 없거나 표가 아니다")
    attack = l3.get("intel", {}).get("attack") if isinstance(l3.get("intel"), dict) else None
    version = attack.get("version") if isinstance(attack, dict) else None
    if not isinstance(version, str) or not version:
        raise ConfigError("l3.intel.attack.version이 없다")
    collect_before = hunt.get("collect_before")
    if not isinstance(collect_before, bool):
        raise ConfigError("l3.hunt.collect_before는 true 또는 false여야 한다")
    threshold = _number(hunt, "confirm_threshold")
    if not 0 <= threshold <= 1:
        raise ConfigError("l3.hunt.confirm_threshold는 0~1이어야 한다")
    return HuntSettings(
        collect_before=collect_before,
        news_window_days=_positive(hunt, "news_window_days"),
        news_limit=_count(hunt, "news_limit", minimum=1),
        case_limit=_count(hunt, "case_limit", minimum=0),
        max_hypotheses=_count(hunt, "max_hypotheses", minimum=1),
        lookback_days=_positive(hunt, "lookback_days"),
        confirm_threshold=threshold,
        max_attempts=_count(hunt, "max_attempts", minimum=1),
        attack_version=version,
    )
