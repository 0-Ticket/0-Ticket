"""벡터 저장소 설정 로더. [store]만 읽어 검사한다(#257).

config/default.toml(커밋함) 위에 config/local.toml(커밋 안 함)을 덮어쓴다(설정 파일 TOML, D-002).
읽기·합치기는 soc.ingest.config와 같은 규칙이다. 공통 설정 로더가 생기면 그것으로 바꾼다.

이 모듈은 TOML 값만 본다. Qdrant 주소 환경변수의 값은 읽지 않는다. 그래서 QDRANT_URL이 없는
곳(기본 pytest, CI check job)에서도 설정을 읽을 수 있다. 환경변수는 클라이언트를 만들 때 읽는다
(soc.store.qdrant.create_client).
"""

import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(__file__).resolve().parents[3] / "config"
# 환경변수 이름. 셸이 받는 모양으로 제한한다.
_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# Hugging Face revision은 커밋 해시로 고정한다(D-031). 태그·브랜치는 받지 않는다.
_REVISION = re.compile(r"[0-9a-f]{40}")


class ConfigError(ValueError):
    """[store] 설정이 올바르지 않다."""


@dataclass(frozen=True)
class QdrantSettings:
    """Qdrant 접속 설정.

    필드:
        url_env: Qdrant 주소를 담은 환경변수 이름. 주소 값은 설정에 두지 않는다.
    """

    url_env: str


@dataclass(frozen=True)
class EmbedderSettings:
    """임베딩 모델 설정(D-031).

    필드:
        model_id: Hugging Face 모델 ID(예: BAAI/bge-m3).
        revision: 내려받을 커밋 해시. 40자 소문자 16진수다.
    """

    model_id: str
    revision: str


@dataclass(frozen=True)
class StoreSettings:
    """read_settings()가 검사를 통과시킨 [store] 값."""

    qdrant: QdrantSettings
    embedder: EmbedderSettings


def load_config(directory: Path | None = None) -> dict[str, Any]:
    """설정 파일을 읽어 합친 뒤 [store] 표만 돌려준다.

    인자:
        directory: default.toml과 local.toml이 있는 폴더. None이면 저장소의 config/를 쓴다.

    반환:
        {"store": {...}}. 설정 파일에 [store]가 없으면 빈 객체다.
    """
    directory = CONFIG_DIR if directory is None else directory
    merged = _read(directory / "default.toml")
    local = directory / "local.toml"
    if local.exists():
        merged = _merge(merged, _read(local))
    return {"store": merged.get("store", {})}


def read_settings(store: dict[str, Any]) -> StoreSettings:
    """[store] 표를 검사해 StoreSettings로 바꾼다.

    인자:
        store: load_config()["store"]가 돌려준 표.

    반환:
        검사를 통과한 StoreSettings.

    발생:
        ConfigError: 표가 없거나 값의 모양이 맞지 않을 때.
    """
    qdrant = _table(store, "qdrant")
    embedder = _table(store, "embedder")
    url_env = _text(qdrant, "url_env", "store.qdrant", _ENV_NAME)
    model_id = _text(embedder, "model_id", "store.embedder")
    revision = _text(embedder, "revision", "store.embedder", _REVISION)
    return StoreSettings(
        qdrant=QdrantSettings(url_env=url_env),
        embedder=EmbedderSettings(model_id=model_id, revision=revision),
    )


def _table(parent: dict[str, Any], key: str) -> dict[str, Any]:
    """parent[key]가 표인지 확인하고 돌려준다. 아니면 ConfigError."""
    value = parent.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"store.{key} 표가 없다")
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
        raise ConfigError(f"{where}.{key}의 모양이 올바르지 않다")
    return value


def _read(path: Path) -> dict[str, Any]:
    """TOML 파일 하나를 dict로 읽는다."""
    with path.open("rb") as f:
        return tomllib.load(f)


def _merge(base: dict[str, Any], over: dict[str, Any]) -> dict[str, Any]:
    """두 설정을 합친다. 표끼리는 안쪽까지 합치고, 그 밖의 값은 over가 이긴다."""
    out = dict(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out
