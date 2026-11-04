"""수집 설정 로더. [ingest]만 읽어 검사한다.

config/default.toml(커밋함) 위에 config/local.toml(커밋 안 함)을 덮어쓴다(설정 파일 TOML, D-002).
덮어쓰기 규칙은 soc.l3.config와 같다. 그 모듈의 읽기·합치기 함수는 비공개라 여기에 같은 코드를
따로 둔다. 공통 설정 로더가 생기면 그것으로 바꾼다.
"""

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"
KINDS = ("alert", "event")
# ELK 기본 index.max_result_window. 한 페이지가 이보다 크면 ELK가 거부한다.
MAX_PAGE_SIZE = 10_000
# 조회 대상은 URL 경로(/{key}/_pit)에 들어간다. 경로·질의를 바꾸는 /, ?, #, 공백을 받지 않고,
# _로 시작하는 이름(_all 등 API 이름)도 받지 않는다. 여러 대상은 쉼표, 패턴은 *로 쓴다.
_KEY = re.compile(r"[A-Za-z0-9.*,:+-][A-Za-z0-9._*,:+-]*")
_FIELD = re.compile(r"[A-Za-z0-9@_][A-Za-z0-9@._-]*")


class ConfigError(Exception):
    """[ingest] 설정이나 환경변수가 틀렸다."""


@dataclass(frozen=True)
class Source:
    kind: str
    key: str
    time_field: str

    @property
    def name(self) -> str:
        """출력에 쓰는 이름. 설정에 적은 값이라 비밀이 아니다."""
        return f"{self.kind}:{self.key}"


@dataclass(frozen=True)
class Settings:
    siem_profile: str
    url_env: str
    api_key_env: str
    page_size: int
    connect_timeout_seconds: float
    read_timeout_seconds: float
    # 응답 하나(PIT 열기, 페이지 하나)마다의 크기 상한과 마감 시간
    max_bytes: int
    deadline_seconds: float
    sources: tuple[Source, ...]


def load_config(directory: Path | None = None) -> dict[str, Any]:
    """{"ingest": {...}}. 설정 파일에 [ingest]가 없으면 빈 객체다."""
    directory = CONFIG_DIR if directory is None else directory
    merged = _read(directory / "default.toml")
    local = directory / "local.toml"
    if local.exists():
        merged = _merge(merged, _read(local))
    return {"ingest": merged.get("ingest", {})}


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


def _positive(parent: dict[str, Any], key: str, where: str) -> int | float:
    value = parent.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise ConfigError(f"{where}.{key}는 0보다 큰 수여야 한다")
    return value


def _text(parent: dict[str, Any], key: str, where: str, pattern: re.Pattern | None = None) -> str:
    value = parent.get(key)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{where}.{key}는 빈 값이 아닌 문자열이어야 한다")
    if pattern is not None and not pattern.fullmatch(value):
        raise ConfigError(f"{where}.{key}에 쓸 수 없는 문자가 있다")
    return value


def read_settings(ingest: dict[str, Any]) -> Settings:
    """load_config()["ingest"]를 검사해 Settings로 바꾼다. 틀리면 ConfigError."""
    where = "ingest"
    page_size = _positive(ingest, "page_size", where)
    if not isinstance(page_size, int) or page_size > MAX_PAGE_SIZE:
        raise ConfigError(f"{where}.page_size는 {MAX_PAGE_SIZE} 이하의 정수여야 한다")

    raw_sources = ingest.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ConfigError(f"{where}.sources가 없거나 비어 있다")
    sources = []
    for index, raw in enumerate(raw_sources):
        at = f"{where}.sources[{index}]"
        if not isinstance(raw, dict):
            raise ConfigError(f"{at}가 표가 아니다")
        kind = _text(raw, "kind", at)
        if kind not in KINDS:
            raise ConfigError(f"{at}.kind는 {', '.join(KINDS)} 중 하나여야 한다")
        sources.append(
            Source(
                kind=kind,
                key=_text(raw, "key", at, _KEY),
                time_field=_text(raw, "time_field", at, _FIELD),
            )
        )
    # 체크포인트는 (siem_profile, kind, key)마다 하나라 같은 대상이 두 번 있으면 서로 덮어쓴다.
    if len({s.name for s in sources}) != len(sources):
        raise ConfigError(f"{where}.sources에 같은 kind·key가 두 번 있다")

    return Settings(
        siem_profile=_text(ingest, "siem_profile", where),
        url_env=_text(ingest, "url_env", where),
        api_key_env=_text(ingest, "api_key_env", where),
        page_size=page_size,
        connect_timeout_seconds=float(_positive(ingest, "connect_timeout_seconds", where)),
        read_timeout_seconds=float(_positive(ingest, "read_timeout_seconds", where)),
        max_bytes=int(_positive(ingest, "max_bytes", where)),
        deadline_seconds=float(_positive(ingest, "deadline_seconds", where)),
        sources=tuple(sources),
    )
