"""L2 설정 로더와 분류 설정 검증."""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"
ENTITY_TYPES = frozenset({"ip", "host", "user", "domain", "url", "file_hash", "process"})
_BRANCH_KEYS = {
    "candidate_window_ms",
    "max_candidates",
    "strong_signal_types",
    "weak_signal_types",
    "shared_entity_values",
}


class ConfigError(ValueError):
    """L2 설정이 올바르지 않다."""


@dataclass(frozen=True)
class BranchSettings:
    candidate_window_ms: int
    max_candidates: int
    strong_signal_types: frozenset[str]
    weak_signal_types: frozenset[str]
    shared_entity_values: tuple[str, ...]


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
        strong = _entity_types(branch["strong_signal_types"])
        weak = _entity_types(branch["weak_signal_types"])
        shared = _strings(branch["shared_entity_values"])
    except (KeyError, TypeError):
        raise ConfigError("L2 branch 설정이 올바르지 않다") from None

    if strong & weak or strong | weak != ENTITY_TYPES:
        raise ConfigError("강한·보조 신호 종류가 겹치거나 빠졌다")
    return BranchSettings(candidate_window_ms, max_candidates, strong, weak, shared)


def _positive_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ConfigError("L2 branch의 수 설정은 양의 정수여야 한다")
    return value


def _entity_types(value: object) -> frozenset[str]:
    values = _strings(value)
    if len(values) != len(set(values)) or not set(values) <= ENTITY_TYPES:
        raise ConfigError("L2 branch 신호 종류가 올바르지 않다")
    return frozenset(values)


def _strings(value: object) -> tuple[str, ...]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item.strip() for item in value
    ):
        raise ConfigError("L2 branch 목록 설정이 올바르지 않다")
    values = tuple(item.strip() for item in value)
    if len(values) != len(set(values)):
        raise ConfigError("L2 branch 목록 설정에 중복이 있다")
    return values


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
