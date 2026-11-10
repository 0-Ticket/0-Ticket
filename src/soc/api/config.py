"""화면용 API 설정 로더(#239). [api], [auth](#284), 기법 이름용 [l3.intel.attack] version만 읽는다.

config/default.toml(커밋함) 위에 config/local.toml(커밋 안 함)을 덮어쓴다(설정 파일 TOML, D-002).
덮어쓰기 규칙은 L3·L2 로더와 같다. 공통 설정 로더가 생기면 그것으로 바꾼다.
"""

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from soc.l3.config import load_config as load_l3_config

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"


class ConfigError(Exception):
    """설정 값이 틀렸다. 메시지에는 키 이름과 허용 범위만 넣는다."""


# 쿠키 이름은 토큰 문자만, 허용 Origin은 스킴+호스트(+포트)만 받는다(경로·와일드카드 없음)
_COOKIE_NAME = re.compile(r"[A-Za-z0-9_-]{1,64}")
_ORIGIN = re.compile(r"https?://[A-Za-z0-9.\-]+(:[0-9]{1,5})?")


@dataclass(frozen=True)
class AuthSettings:
    idle_timeout_seconds: int
    absolute_timeout_seconds: int
    cookie_name: str
    cookie_secure: bool
    allowed_origins: tuple[str, ...]


@dataclass(frozen=True)
class ApiSettings:
    host: str
    port: int
    statement_timeout_ms: int
    connect_timeout_seconds: int
    attack_version: str
    auth: AuthSettings


def load_config(directory: Path | None = None) -> dict[str, Any]:
    """{"api": {...}, "auth": {...}}. 설정 파일에 없는 절은 빈 객체다."""
    directory = CONFIG_DIR if directory is None else directory
    merged = _read(directory / "default.toml")
    local = directory / "local.toml"
    if local.exists():
        merged = _merge(merged, _read(local))
    return {"api": merged.get("api", {}), "auth": merged.get("auth", {})}


def load_settings(directory: Path | None = None) -> ApiSettings:
    config = load_config(directory)
    api = config["api"]
    attack = load_l3_config(directory)["l3"].get("intel", {}).get("attack", {})
    version = attack.get("version")
    if not isinstance(version, str) or not version:
        raise ConfigError("[l3.intel.attack] version은 빈 값이 아닌 문자열이어야 한다")
    host = api.get("host")
    if not isinstance(host, str) or not host:
        raise ConfigError("[api] host는 빈 값이 아닌 문자열이어야 한다")
    return ApiSettings(
        host=host,
        port=_int(api, "port", 1, 65535),
        statement_timeout_ms=_int(api, "statement_timeout_ms", 1, 2_147_483_647),
        connect_timeout_seconds=_int(api, "connect_timeout_seconds", 1, 3600),
        attack_version=version,
        auth=_auth(config["auth"]),
    )


def _auth(auth: dict[str, Any]) -> AuthSettings:
    name = auth.get("cookie_name")
    if not isinstance(name, str) or not _COOKIE_NAME.fullmatch(name):
        raise ConfigError("[auth] cookie_name은 영숫자, _, -로 된 1~64자여야 한다")
    secure = auth.get("cookie_secure")
    if type(secure) is not bool:
        raise ConfigError("[auth] cookie_secure는 true 또는 false여야 한다")
    origins = auth.get("allowed_origins")
    if (
        not isinstance(origins, list)
        or not origins
        or not all(isinstance(o, str) and _ORIGIN.fullmatch(o) for o in origins)
    ):
        raise ConfigError(
            "[auth] allowed_origins는 http(s)://호스트[:포트] 문자열의 비지 않은 목록이어야 한다"
        )
    return AuthSettings(
        idle_timeout_seconds=_int(auth, "idle_timeout_seconds", 1, 31_536_000, "auth"),
        absolute_timeout_seconds=_int(auth, "absolute_timeout_seconds", 1, 31_536_000, "auth"),
        cookie_name=name,
        cookie_secure=secure,
        allowed_origins=tuple(origins),
    )


def _int(section: dict[str, Any], key: str, low: int, high: int, name: str = "api") -> int:
    value = section.get(key)
    if type(value) is not int or not low <= value <= high:
        raise ConfigError(f"[{name}] {key}는 {low}~{high} 정수여야 한다")
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
