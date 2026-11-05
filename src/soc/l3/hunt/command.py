"""uv run python -m soc.l3 hunt의 본체: 수집 → 가설 생성 run 1회 → pending Hunt 전부 검증.

출력은 건수와 실패 종류만이다. 가설·이유·뉴스 같은 본문과 DB 주소는 출력하지 않는다.
종료 코드: 0 정상(가설 0건, 일부 Hunt failed 포함), 1 가설 생성 run 실패 또는 DB 오류, 2 설정 오류.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import httpx
import psycopg

from soc.agent import run_agent
from soc.l3.hunt import store
from soc.l3.hunt.hypothesize import HypothesizeResult, Run, hypothesize
from soc.l3.hunt.settings import ConfigError, read_hunt_settings
from soc.l3.hunt.verify import HuntVerifier
from soc.l3.intel import collect as intel

STATUSES = ("confirmed", "rejected", "inconclusive", "pending", "failed")


def _utcnow() -> datetime:
    return datetime.now(UTC)


def run_hunt(
    l3: dict[str, Any],
    database_url: str | None,
    *,
    run: Run = run_agent,
    client_factory: Callable[[intel.Settings], httpx.Client] = intel.make_client,
    clock: Callable[[], datetime] = _utcnow,
    out: Callable[[str], None] = print,
    err: Callable[[str], None] = print,
) -> int:
    try:
        settings = read_hunt_settings(l3)
        intel_settings = intel.read_settings(l3) if settings.collect_before else None
    except (ConfigError, intel.ConfigError) as exc:
        err(f"설정 오류: {exc}")
        return 2
    if not database_url:
        err("환경변수 DATABASE_URL이 없다. .env.example을 참고해 설정한다.")
        return 2

    try:
        with psycopg.connect(database_url, autocommit=True) as conn:
            if intel_settings is not None:
                with client_factory(intel_settings) as client:
                    results = intel.collect(intel_settings, conn, client, now=clock())
                for line in intel.format_results(results):
                    out(f"수집 {line}")  # 실패한 출처가 있어도 저장된 뉴스로 계속한다
            made = hypothesize(conn, settings, run=run, now=clock())
            out(_format_hypothesize(made, settings.attack_version))
            verifier = HuntVerifier(database_url, settings, run=run, clock=clock)
            hunt_ids = verifier.poll(None)
            for hunt_id in hunt_ids:
                verifier.handle(hunt_id)
            counts = store.status_counts(conn, hunt_ids)
    except psycopg.Error as exc:
        # 원래 예외 메시지에는 접속 대상 주소가 들어 있을 수 있어 종류만 남긴다.
        err(f"DB 오류({type(exc).__name__}). DATABASE_URL과 마이그레이션을 확인한다")
        return 1
    summary = ", ".join(f"{s} {counts.get(s, 0)}" for s in STATUSES)
    out(f"검증: Hunt {len(hunt_ids)}건 / {summary}")
    return 1 if made.failure else 0


def _format_hypothesize(made: HypothesizeResult, attack_version: str) -> str:
    if made.skipped == "no_attack_version":
        return f"가설 생성: 건너뜀(ATT&CK {attack_version} 기법이 DB에 없다. 수집을 먼저 한다)"
    return (
        f"가설 생성: 저장 {len(made.saved)}, 없는 기법으로 버림 {made.unknown_technique},"
        f" 한도 초과로 버림 {made.over_limit}, 버린 참조 {made.dropped_refs},"
        f" 실패 {made.failure or '없음'}"
    )
