"""L2 설정 로더와 분류 설정 검증."""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"
_BRANCH_KEYS = {
    "candidate_window_ms",
    "max_candidates",
    "candidate_source",
    "top_k",
}


class ConfigError(ValueError):
    """L2 설정이 올바르지 않다."""


@dataclass(frozen=True)
class BranchSettings:
    candidate_window_ms: int
    max_candidates: int
    candidate_source: str
    top_k: int


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
        candidate_source = branch["candidate_source"]
        top_k = _positive_int(branch["top_k"])
    except (KeyError, TypeError):
        raise ConfigError("L2 branch 설정이 올바르지 않다") from None

    if candidate_source not in ("vector", "recent"):
        raise ConfigError("L2 branch candidate_source는 vector 또는 recent여야 한다")
    return BranchSettings(candidate_window_ms, max_candidates, candidate_source, top_k)


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
