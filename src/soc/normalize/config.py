"""정규화 설정 로더. [normalize]와 [asset_lookup]을 읽는다.

config/default.toml(커밋함) 위에 config/local.toml(커밋 안 함)을 덮어쓴다(설정 파일 TOML, D-002).
덮어쓰기 규칙은 다른 패키지의 로더와 같다. 공통 설정 로더가 생기면 그것으로 바꾼다.
"""

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


class ConfigError(Exception):
    """설정 값이 틀렸다. 메시지에는 키 이름과 허용 범위만 넣는다."""


@dataclass(frozen=True)
class Settings:
    """정규화 실행 설정.

    Attributes:
        batch_size: 한 번 실행에서 맡는 원본 수.
        lease_seconds: 작업자가 한 묶음을 맡는 시간(초). 묶음을 다 처리하는 시간보다 길어야 하고,
            넘으면 다음 작업자가 아직 처리하지 못한 원본을 다시 맡을 수 있다.
        connect_timeout_seconds: 결과를 저장하는 DB의 접속 시간 상한(초).
        asset_statement_timeout_ms: 자산 조회 문장 하나의 시간 상한(밀리초).
    """

    batch_size: int
    lease_seconds: int
    connect_timeout_seconds: int
    asset_statement_timeout_ms: int


def load_settings(directory: Path | None = None) -> Settings:
    """설정 파일을 읽어 검사한 Settings를 돌려준다.

    Args:
        directory: default.toml과 local.toml이 있는 폴더. 없으면 저장소 config/.

    Raises:
        ConfigError: 값이 없거나 범위를 벗어났다.
    """
    directory = CONFIG_DIR if directory is None else directory
    merged = _read(directory / "default.toml")
    local = directory / "local.toml"
    if local.exists():
        merged = _merge(merged, _read(local))
    normalize = merged.get("normalize", {})
    asset_lookup = merged.get("asset_lookup", {})
    return Settings(
        batch_size=_int(normalize, "normalize", "batch_size", 1, 10_000),
        lease_seconds=_int(normalize, "normalize", "lease_seconds", 1, 86_400),
        connect_timeout_seconds=_int(normalize, "normalize", "connect_timeout_seconds", 1, 3600),
        asset_statement_timeout_ms=_int(
            asset_lookup, "asset_lookup", "statement_timeout_ms", 1, 2_147_483_647
        ),
    )


def _int(table: dict[str, Any], section: str, key: str, low: int, high: int) -> int:
    """설정 값 하나를 low~high 정수로 읽는다.

    Args:
        table: 값이 든 설정 표.
        section: 오류 메시지에 쓸 표 이름.
        key: 읽을 키.
        low: 허용하는 최솟값.
        high: 허용하는 최댓값.

    Raises:
        ConfigError: 값이 없거나 정수가 아니거나 범위를 벗어났다.
    """
    value = table.get(key)
    if type(value) is not int or not low <= value <= high:
        raise ConfigError(f"[{section}] {key}는 {low}~{high} 정수여야 한다")
    return value


def _read(path: Path) -> dict[str, Any]:
    """TOML 파일 하나를 읽는다.

    Args:
        path: 읽을 파일.
    """
    with path.open("rb") as f:
        return tomllib.load(f)


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """표 안쪽까지 재귀로 합친다. 같은 키는 over가 이긴다.

    Args:
        base: 기본 설정.
        over: 덮어쓸 설정.
    """
    out = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out
