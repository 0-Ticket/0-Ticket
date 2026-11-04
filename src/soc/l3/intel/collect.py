"""설정의 출처를 차례로 가져와 저장한다. 한 출처가 실패해도 나머지를 계속한다.

출처마다 트랜잭션 하나로 저장하고, 실패하면 그 출처만 되돌린다. DB 오류는 출처 실패가 아니라
환경 문제라 그대로 올린다.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
import psycopg

from soc.l3.intel import parse, store
from soc.l3.intel.errors import IntelError
from soc.l3.intel.fetch import fetch

KINDS = ("rss", "cisa_kev")
ATTACK_NAME = "attack"


class ConfigError(Exception):
    """[l3.intel] 설정이 틀렸다."""


@dataclass(frozen=True)
class Limit:
    max_bytes: int
    deadline_seconds: float


@dataclass(frozen=True)
class Source:
    name: str
    kind: str
    url: str


@dataclass(frozen=True)
class Attack:
    version: str
    url: str
    limit: Limit


@dataclass(frozen=True)
class Settings:
    sources: tuple[Source, ...]
    attack: Attack
    limits: dict[str, Limit]
    summary_max_chars: int
    connect_timeout_seconds: float
    read_timeout_seconds: float


@dataclass
class SourceResult:
    name: str
    fetched: int = 0
    inserted: int = 0
    updated: int = 0
    failure: str | None = None
    skipped: bool = False
    version: str | None = None


def _table(parent: dict[str, Any], key: str, where: str) -> dict[str, Any]:
    value = parent.get(key)
    if not isinstance(value, dict):
        raise ConfigError(f"{where}.{key}가 없거나 표가 아니다")
    return value


def _positive(parent: dict[str, Any], key: str, where: str) -> int | float:
    value = parent.get(key)
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise ConfigError(f"{where}.{key}는 0보다 큰 수여야 한다")
    return value


def _text(parent: dict[str, Any], key: str, where: str) -> str:
    value = parent.get(key)
    if not isinstance(value, str) or not value:
        raise ConfigError(f"{where}.{key}는 빈 값이 아닌 문자열이어야 한다")
    return value


def _url(parent: dict[str, Any], where: str) -> str:
    url = _text(parent, "url", where)
    if not url.startswith("https://"):
        raise ConfigError(f"{where}.url은 https 주소여야 한다")
    return url


def _limit(table: dict[str, Any], where: str) -> Limit:
    return Limit(
        max_bytes=int(_positive(table, "max_bytes", where)),
        deadline_seconds=float(_positive(table, "deadline_seconds", where)),
    )


def read_settings(l3: dict[str, Any]) -> Settings:
    """load_config()["l3"]을 검사해 Settings로 바꾼다. 틀리면 ConfigError."""
    intel = _table(l3, "intel", "l3")
    where = "l3.intel"
    limits_table = _table(intel, "limits", where)
    limits = {
        kind: _limit(_table(limits_table, kind, f"{where}.limits"), f"{where}.limits.{kind}")
        for kind in KINDS
    }

    raw_sources = intel.get("sources")
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
        sources.append(Source(name=_text(raw, "name", at), kind=kind, url=_url(raw, at)))
    names = [s.name for s in sources] + [ATTACK_NAME]
    if len(set(names)) != len(names):
        raise ConfigError(f"{where}.sources의 name이 겹친다('{ATTACK_NAME}'은 ATT&CK이 쓴다)")

    attack = _table(intel, "attack", where)
    return Settings(
        sources=tuple(sources),
        attack=Attack(
            version=_text(attack, "version", f"{where}.attack"),
            url=_url(attack, f"{where}.attack"),
            limit=_limit(attack, f"{where}.attack"),
        ),
        limits=limits,
        summary_max_chars=int(_positive(intel, "summary_max_chars", where)),
        connect_timeout_seconds=float(_positive(intel, "connect_timeout_seconds", where)),
        read_timeout_seconds=float(_positive(intel, "read_timeout_seconds", where)),
    )


def make_client(settings: Settings) -> httpx.Client:
    timeout = httpx.Timeout(
        settings.read_timeout_seconds,
        connect=settings.connect_timeout_seconds,
    )
    return httpx.Client(timeout=timeout, follow_redirects=False)


def collect(
    settings: Settings,
    conn: psycopg.Connection,
    client: httpx.Client,
    *,
    now: datetime,
    clock: Callable[[], float] = time.monotonic,
) -> list[SourceResult]:
    """뉴스 출처를 설정 순서대로, 마지막에 ATT&CK을 처리한다. conn은 autocommit 연결이다."""
    results = []
    for source in settings.sources:
        result = SourceResult(name=source.name)
        limit = settings.limits[source.kind]
        try:
            data = fetch(
                client,
                source.url,
                max_bytes=limit.max_bytes,
                deadline_seconds=limit.deadline_seconds,
                clock=clock,
            )
            reader = parse.parse_rss if source.kind == "rss" else parse.parse_kev
            items = reader(data, summary_max_chars=settings.summary_max_chars)
        except IntelError as exc:
            result.failure = exc.kind
        else:
            result.fetched = len(items)
            with conn.transaction():
                result.inserted, result.updated = store.save_news(
                    conn, source=source.name, kind=source.kind, items=items, now=now
                )
        results.append(result)
    results.append(_collect_attack(settings.attack, conn, client, clock))
    return results


def _collect_attack(
    attack: Attack,
    conn: psycopg.Connection,
    client: httpx.Client,
    clock: Callable[[], float],
) -> SourceResult:
    result = SourceResult(name=ATTACK_NAME, version=attack.version)
    if store.has_attack_version(conn, attack.version):
        result.skipped = True
        return result
    try:
        data = fetch(
            client,
            attack.url,
            max_bytes=attack.limit.max_bytes,
            deadline_seconds=attack.limit.deadline_seconds,
            clock=clock,
        )
        techniques = parse.parse_attack(data, version=attack.version)
    except IntelError as exc:
        result.failure = exc.kind
        return result
    result.fetched = len(techniques)
    with conn.transaction():
        result.inserted = store.save_attack(conn, attack.version, techniques)
    return result


def format_results(results: list[SourceResult]) -> list[str]:
    """출처마다 한 줄. 건수와 실패 종류만 쓰고 본문·응답 내용은 쓰지 않는다."""
    lines = []
    for r in results:
        if r.skipped:
            lines.append(f"{r.name}: 버전 {r.version}이 이미 있어 건너뜀")
            continue
        lines.append(
            f"{r.name}: 가져옴 {r.fetched}, 새로 저장 {r.inserted}, 갱신 {r.updated},"
            f" 실패 {r.failure or '없음'}"
        )
    return lines


def exit_code(results: list[SourceResult]) -> int:
    return 1 if any(r.failure for r in results) else 0
