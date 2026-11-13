"""활성화 파이프 준비 점검(#316).

항목마다 OK / FAIL / SKIP 한 줄만 낸다. FAIL에는 실패 종류 코드(예외 클래스 이름 등)만 붙이고,
주소·계정·키 값과 예외 메시지는 내지 않는다. 하나가 FAIL이어도 나머지 항목을 모두 돌린다.
네트워크·DB에 닿는 부분은 Probes로 갈아 끼울 수 있어 테스트가 가짜 연결로 실패를 만든다.
"""

import asyncio
import copy
import os
import ssl
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

import psycopg

from soc.agent.llm import build_client
from soc.api.db import DATABASE_URL_ENV
from soc.db.migrate import unapplied_migrations
from soc.tools import default_registry
from soc.tools.db import DATABASE_URL_ENV as AGENT_DATABASE_URL_ENV

Probe = Callable[[dict[str, Any]], None]
SIMILAR_TOOL = "search_similar_cases"
CONNECT_TIMEOUT = 5


class MigrationsPending(Exception):
    """적용하지 않은 마이그레이션이 있다."""


@dataclass(frozen=True)
class Check:
    name: str
    status: str  # OK | FAIL | SKIP
    code: str | None = None


def format_check(check: Check) -> str:
    if check.status == "OK":
        return f"OK   {check.name}"
    if check.status == "SKIP":
        return f"SKIP {check.name}"
    return f"FAIL {check.name} ({check.code})"


def _select_one(url: str) -> None:
    with psycopg.connect(url, connect_timeout=CONNECT_TIMEOUT) as conn:
        conn.execute("SELECT 1")


def probe_db(config: dict[str, Any]) -> None:
    _select_one(os.environ[DATABASE_URL_ENV])


def probe_migrations(config: dict[str, Any]) -> None:
    if unapplied_migrations(os.environ[DATABASE_URL_ENV]):
        raise MigrationsPending


def probe_agent_db(config: dict[str, Any]) -> None:
    _select_one(os.environ[AGENT_DATABASE_URL_ENV])


def probe_qdrant(config: dict[str, Any]) -> None:
    from soc.store.config import read_settings
    from soc.store.qdrant import create_client

    client = create_client(read_settings(config["store"]).qdrant, timeout=CONNECT_TIMEOUT)
    try:
        client.get_collections()
    finally:
        client.close()


def probe_embedder(config: dict[str, Any]) -> None:
    from soc.store.config import read_settings
    from soc.store.embedder import ONNX_DATA_FILE, BgeM3Embedder, _model_dir

    settings = read_settings(config["store"]).embedder
    if not (_model_dir(settings) / ONNX_DATA_FILE).exists():
        print("임베딩 모델 파일이 없다. 약 2.27GB를 내려받는 중이다(처음 한 번)", flush=True)
    BgeM3Embedder(settings).embed("ping")


def probe_llm(config: dict[str, Any]) -> None:
    async def ping() -> None:
        client, model = build_client(config)
        try:
            # 고정 문자열 한 건. 로그·DB 값은 보내지 않는다. 키가 틀리면 L1이 첫 건부터 실패를 센다
            await client.chat.completions.create(
                model=model, messages=[{"role": "user", "content": "ping"}], max_tokens=16
            )
        finally:
            await client.close()

    asyncio.run(ping())


@dataclass(frozen=True)
class Probes:
    db: Probe = field(default=probe_db)
    migrations: Probe = field(default=probe_migrations)
    agent_db: Probe = field(default=probe_agent_db)
    qdrant: Probe = field(default=probe_qdrant)
    embedder: Probe = field(default=probe_embedder)
    llm: Probe = field(default=probe_llm)


def run_checks(
    config: Mapping[str, Any], probes: Probes, environ: Mapping[str, str]
) -> list[Check]:
    cfg = copy.deepcopy(dict(config))
    allowed = [n for s in ("l1", "l2") for n in cfg.get("tools", {}).get("allowed", {}).get(s, [])]
    registry = default_registry()
    bundles = {registry.get(n).bundle for n in allowed if registry.get(n) is not None}
    needs_vector = (
        cfg.get("l2", {}).get("branch", {}).get("candidate_source") == "vector"
        or SIMILAR_TOOL in allowed
    )

    def probed(name: str, probe: Probe, env: str | None = None, *, needed: bool = True) -> Check:
        if not needed:
            return Check(name, "SKIP")
        if env is not None and not environ.get(env):
            return Check(name, "FAIL", "env_missing")
        try:
            probe(cfg)
        except Exception as exc:
            return Check(name, "FAIL", type(exc).__name__)
        return Check(name, "OK")

    return [
        _stages(cfg),
        probed("db", probes.db, DATABASE_URL_ENV),
        probed("migrations", probes.migrations, DATABASE_URL_ENV),
        probed("agent_db", probes.agent_db, AGENT_DATABASE_URL_ENV, needed="internal" in bundles),
        probed("qdrant", probes.qdrant, needed=needs_vector),
        probed("embedder", probes.embedder, needed=needs_vector),
        probed("llm", probes.llm),
        _tools(cfg, allowed, bundles, registry.names(), environ),
    ]


def _stages(config: Mapping[str, Any]) -> Check:
    for stage in ("l1", "l2"):
        values = config.get("executor", {}).get(stage, {})
        if not values.get("interval_seconds", 0) > 0 or not values.get("workers"):
            return Check("stages", "FAIL", f"{stage}_off")
    return Check("stages", "OK")


def _tools(
    config: Mapping[str, Any],
    allowed: list[str],
    bundles: set[str],
    registered: list[str],
    environ: Mapping[str, str],
) -> Check:
    if any(name not in registered for name in allowed):
        return Check("tools_config", "FAIL", "unknown_tool")
    if "siem" in bundles:
        siem = config.get("tools", {}).get("siem", {})
        for key in ("url_env", "api_key_env"):
            if not environ.get(str(siem.get(key, ""))):
                return Check("tools_config", "FAIL", "siem_env")
        path = siem.get("ca_cert_path", "")
        if path:
            try:
                ssl.create_default_context(cafile=path)
            except (OSError, ssl.SSLError, TypeError, ValueError):
                return Check("tools_config", "FAIL", "ca_cert")
    return Check("tools_config", "OK")
