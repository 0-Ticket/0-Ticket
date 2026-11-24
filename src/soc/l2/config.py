"""L2 설정 로더와 분류 설정 검증."""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"
_BRANCH_KEYS = {
    "candidate_window_ms",
    "max_candidates",
    "max_incident_tickets",
    "min_score",
    "max_calls_per_cycle",
    "max_failures",
    "failure_retry_delay_ms",
}
_ANALYZE_KEYS = (
    "lookback_ms",
    "max_failures",
    "failure_retry_cooldown_ms",
)


class ConfigError(ValueError):
    """L2 설정이 올바르지 않다."""


@dataclass(frozen=True)
class BranchSettings:
    candidate_window_ms: int
    max_candidates: int
    max_incident_tickets: int
    min_score: float = 0.7725
    max_calls_per_cycle: int = 3
    max_failures: int = 3
    failure_retry_delay_ms: int = 300_000


@dataclass(frozen=True)
class AnalyzeSettings:
    lookback_ms: int
    max_failures: int
    failure_retry_cooldown_ms: int


def load_config(directory: Path | None = None) -> dict[str, Any]:
    """{"l2": {...}}. 설정 파일에 [l2]가 없으면 빈 객체다."""
    directory = CONFIG_DIR if directory is None else directory
    merged = _read(directory / "default.toml")
    local = directory / "local.toml"
    if local.exists():
        merged = _merge(merged, _read(local))
    return {"l2": merged.get("l2", {})}


def read_settings(l2: dict[str, Any]) -> BranchSettings:
    """[l2.branch]를 검증해 코드가 쓰는 값으로 바꾼다."""
    try:
        branch = l2["branch"]
        if not isinstance(branch, dict) or set(branch) != _BRANCH_KEYS:
            raise ConfigError("L2 branch 설정 키가 올바르지 않다")
        candidate_window_ms = _positive_int(branch["candidate_window_ms"])
        max_candidates = _positive_int(branch["max_candidates"])
        if max_candidates > 5:
            raise ConfigError("L2 branch max_candidates는 5 이하여야 한다")
        max_incident_tickets = _positive_int(branch["max_incident_tickets"])
        min_score = branch["min_score"]
        if (
            isinstance(min_score, bool)
            or not isinstance(min_score, int | float)
            or not 0 < min_score <= 1
        ):
            raise ConfigError("L2 branch min_score는 0 초과 1 이하여야 한다")
        max_calls_per_cycle = _positive_int(branch["max_calls_per_cycle"])
        if max_calls_per_cycle > 3:
            raise ConfigError("L2 branch max_calls_per_cycle은 3 이하여야 한다")
        max_failures = _positive_int(branch["max_failures"])
        failure_retry_delay_ms = _positive_int(branch["failure_retry_delay_ms"])
    except (KeyError, TypeError):
        raise ConfigError("L2 branch 설정이 올바르지 않다") from None

    return BranchSettings(
        candidate_window_ms,
        max_candidates,
        max_incident_tickets,
        float(min_score),
        max_calls_per_cycle,
        max_failures,
        failure_retry_delay_ms,
    )


def read_analyze_settings(l2: dict[str, Any]) -> AnalyzeSettings:
    """[l2.analyze]를 검증해 코드가 쓰는 값으로 바꾼다."""
    try:
        analyze = l2["analyze"]
        if not isinstance(analyze, dict) or set(analyze) != set(_ANALYZE_KEYS):
            raise ConfigError("L2 analyze 설정 키가 올바르지 않다")
        values = [_positive_int(analyze[key]) for key in _ANALYZE_KEYS]
    except (KeyError, TypeError):
        raise ConfigError("L2 analyze 설정이 올바르지 않다") from None
    return AnalyzeSettings(*values)


def _positive_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError("L2 branch의 수 설정은 양의 정수여야 한다")
    return value


def _read(path: Path) -> dict[str, Any]:
    with path.open("rb") as f:
        return tomllib.load(f)


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out
