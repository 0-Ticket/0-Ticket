"""L3 설정 로더. [l3]만 읽는다.

config/default.toml(커밋함) 위에 config/local.toml(커밋 안 함)을 덮어쓴다(설정 파일 TOML, D-002).
덮어쓰기 규칙은 에이전트 로더(soc.agent.config)와 같다. 에이전트 로더는 바꾸지 않고 따로 둔다.
공통 설정 로더가 생기면 그것으로 바꾼다.
"""

import tomllib
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


def load_config(directory: Path | None = None) -> dict[str, Any]:
    """{"l3": {...}}. 설정 파일에 [l3]이 없으면 빈 객체다."""
    directory = CONFIG_DIR if directory is None else directory
    merged = _read(directory / "default.toml")
    local = directory / "local.toml"
    if local.exists():
        merged = _merge(merged, _read(local))
    return {"l3": merged.get("l3", {})}


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
