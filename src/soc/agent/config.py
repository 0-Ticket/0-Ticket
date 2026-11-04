"""에이전트 계층의 최소 설정 로더. [llm]·[agent]·[tools]만 읽는다.

config/default.toml(커밋함) 위에 config/local.toml(커밋 안 함)을 덮어쓴다(설정 파일 TOML, D-002).
비밀 값은 넣지 않고 환경변수 이름만 적는다. 공통 설정 로더가 생기면 그것으로 바꾼다.
"""

import tomllib
from pathlib import Path
from typing import Any

SECTIONS = ("llm", "agent", "tools")
CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


def load_config(directory: Path | None = None) -> dict[str, Any]:
    directory = CONFIG_DIR if directory is None else directory
    merged = _read(directory / "default.toml")
    local = directory / "local.toml"
    if local.exists():
        merged = _merge(merged, _read(local))
    return {name: merged[name] for name in SECTIONS if name in merged}


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
