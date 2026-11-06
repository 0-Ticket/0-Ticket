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
    """조회 대상 하나. 체크포인트와 RawRecord의 (kind, key)가 된다.

    필드:
        kind: "alert" 또는 "event". RawRecord의 kind와 같다.
        key: ELK 조회 대상(alias, 인덱스·데이터 스트림 패턴). URL 경로(/{key}/_pit)에 들어간다.
        time_field: 정렬과 커서에 쓰는 시각 필드 이름(예: @timestamp).
    """

    kind: str
    key: str
    time_field: str

    @property
    def name(self) -> str:
        """출력에 쓰는 이름. 설정에 적은 값이라 비밀이 아니다."""
        return f"{self.kind}:{self.key}"


@dataclass(frozen=True)
class Settings:
    """수집 실행 설정. read_settings()가 검사한 값만 담는다.

    필드:
        siem_profile: 저장하는 RawRecord·체크포인트의 프로필 이름.
        url_env: ELK 주소를 담은 환경변수 이름. 값은 설정에 두지 않는다.
        api_key_env: ELK API 키를 담은 환경변수 이름. 값은 설정에 두지 않는다.
        page_size: 검색 한 번이 받는 문서 수(1~10000).
        connect_timeout_seconds: 연결 제한 시간(초).
        read_timeout_seconds: 읽기 제한 시간(초). 요청 하나마다 적용한다.
        max_bytes: 응답 하나의 최대 크기(압축을 푼 바이트).
        deadline_seconds: 응답 하나의 전체 마감 시간(초).
        sources: 조회 대상 목록. 설정 파일에 적은 순서대로 처리한다.
        ca_cert_path: 자체 서명 HTTPS ELK의 CA 인증서 파일(PEM) 경로. 빈 값이면 httpx 기본 신뢰
            저장소를 쓴다(#264). 비밀이 아니라 설정 값이다.
    """

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
    ca_cert_path: str = ""


def load_config(directory: Path | None = None) -> dict[str, Any]:
    """설정 파일을 읽어 합친 뒤 [ingest] 표만 돌려준다.

    인자:
        directory: default.toml과 local.toml이 있는 폴더. None이면 저장소의 config/를 쓴다.

    반환:
        {"ingest": {...}}. 설정 파일에 [ingest]가 없으면 빈 객체다.
    """
    directory = CONFIG_DIR if directory is None else directory
    merged = _read(directory / "default.toml")
    local = directory / "local.toml"
    if local.exists():
        merged = _merge(merged, _read(local))
    return {"ingest": merged.get("ingest", {})}


def _read(path: Path) -> dict[str, Any]:
    """TOML 파일 하나를 dict로 읽는다. 인자 path는 파일 경로다."""
    with path.open("rb") as f:
        return tomllib.load(f)


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """두 설정을 합친다. 표(dict)끼리는 안쪽까지 합치고, 그 밖의 값은 over가 이긴다.

    인자:
        base: 기본 설정(default.toml).
        over: 덮어쓸 설정(local.toml).

    반환:
        합친 새 dict. 인자로 받은 dict는 바꾸지 않는다.
    """
    out = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def _positive(parent: dict[str, Any], key: str, where: str) -> int | float:
    """parent[key]가 0보다 큰 수인지 확인하고 돌려준다. 아니면 ConfigError.

    인자:
        parent: 설정 표.
        key: 확인할 키.
        where: 오류 메시지에 쓸 설정 위치(예: "ingest").
    """
    value = parent.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise ConfigError(f"{where}.{key}는 0보다 큰 수여야 한다")
    return value


def _text(parent: dict[str, Any], key: str, where: str, pattern: re.Pattern | None = None) -> str:
    """parent[key]가 빈 값이 아닌 문자열인지 확인하고 돌려준다. 아니면 ConfigError.

    인자:
        parent: 설정 표.
        key: 확인할 키.
        where: 오류 메시지에 쓸 설정 위치.
        pattern: 있으면 값 전체가 이 정규식에 맞아야 한다. None이면 모양은 보지 않는다.
    """
    value = parent.get(key)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{where}.{key}는 빈 값이 아닌 문자열이어야 한다")
    if pattern is not None and not pattern.fullmatch(value):
        raise ConfigError(f"{where}.{key}에 쓸 수 없는 문자가 있다")
    return value


def read_settings(ingest: dict[str, Any]) -> Settings:
    """[ingest] 표를 검사해 Settings로 바꾼다.

    인자:
        ingest: load_config()["ingest"]가 돌려준 표.

    반환:
        검사를 통과한 Settings.

    발생:
        ConfigError: 값이 없거나 범위·모양이 맞지 않거나, 같은 (kind, key)가 두 번 있을 때.
    """
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

    # 없으면 빈 값(기본 신뢰 저장소). 파일은 여기서 읽지 않고 elk.tls_verify가 읽는다.
    ca_cert_path = ingest.get("ca_cert_path", "")
    if not isinstance(ca_cert_path, str):
        raise ConfigError(f"{where}.ca_cert_path는 문자열이어야 한다")

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
        ca_cert_path=ca_cert_path,
    )
