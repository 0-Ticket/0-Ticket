"""생성 워커(#245): 차례가 되면 수집 → 가설 생성 run → pending Hunt 저장을 한다.

실행기(#215)에 [executor.l3] workers의 "soc.l3.hunt.generate:build_worker"로 등록한다. 같은 단계의
검증 워커보다 앞에 두면, 새로 만든 Hunt가 같은 라운드에서 검증된다.

- 차례: 마지막 시도부터 [l3.hunt] generate_interval_seconds가 지났다. 마지막 시도는 DB(cancelled가
  아닌 l3_hypothesize Agent Log)와 이 프로세스 안 기록 중 늦은 것이다. 프로세스 안 기록은 handle을
  시작할 때 남겨, Agent Log가 남지 않는 경우(ATT&CK 없음으로 건너뜀, 모델을 부르기 전 실패, 예외)도
  재시작 전까지 매 라운드 반복하지 않는다.
- 가설 생성 run이 실패해도 한 번의 시도다. 다음 시도는 간격이 지난 뒤다.
- 로그에는 건수와 실패 종류만 남긴다. 가설·뉴스 같은 본문은 남기지 않는다.

수집 → 가설 생성(collect_and_hypothesize)은 수동 명령(soc.l3 hunt)도 쓴다.
"""

import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import psycopg

from soc.agent import run_agent
from soc.l3.hunt import store
from soc.l3.hunt.hypothesize import TASK, HypothesizeResult, Run, hypothesize
from soc.l3.hunt.settings import ConfigError, HuntSettings, read_hunt_settings
from soc.l3.hunt.verify import database_url_from_env
from soc.l3.intel import collect as intel

logger = logging.getLogger("soc.l3.hunt.generate")

# 표시 ID. 생성에는 대상이 따로 없어 poll이 이 값 하나를 낸다
SUBJECT_ID = "hypothesize"

ClientFactory = Callable[[intel.Settings], httpx.Client]


def _utcnow() -> datetime:
    return datetime.now(UTC)


def collect_and_hypothesize(
    conn: psycopg.Connection,
    settings: HuntSettings,
    intel_settings: intel.Settings | None,
    *,
    run: Run,
    client_factory: ClientFactory,
    clock: Callable[[], datetime],
    out: Callable[[str], None],
) -> HypothesizeResult:
    """intel_settings가 있으면 수집하고(출처가 실패해도 저장된 뉴스로 계속), 가설 생성 run을 한다.

    출처별 결과 줄(건수·실패 종류)을 out으로 낸다. DB 오류(psycopg.Error)는 그대로 올린다.
    """
    if intel_settings is not None:
        with client_factory(intel_settings) as client:
            results = intel.collect(intel_settings, conn, client, now=clock())
        for line in intel.format_results(results):
            out(f"수집 {line}")
    return hypothesize(conn, settings, run=run, now=clock())


def format_hypothesize(made: HypothesizeResult, attack_version: str) -> str:
    """가설 생성 결과 한 줄. 건수와 실패 종류만 쓴다."""
    if made.skipped == "no_attack_version":
        return f"가설 생성: 건너뜀(ATT&CK {attack_version} 기법이 DB에 없다. 수집을 먼저 한다)"
    return (
        f"가설 생성: 저장 {len(made.saved)}, 없는 기법으로 버림 {made.unknown_technique},"
        f" 한도 초과로 버림 {made.over_limit}, 버린 참조 {made.dropped_refs},"
        f" 실패 {made.failure or '없음'}"
    )


class HuntGenerator:
    stage = "l3"
    name = "l3_hunt_hypothesize"

    def __init__(
        self,
        database_url: str,
        settings: HuntSettings,
        intel_settings: intel.Settings | None,
        *,
        interval_seconds: float,
        run: Run = run_agent,
        client_factory: ClientFactory = intel.make_client,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self._database_url = database_url
        self._settings = settings
        self._intel_settings = intel_settings
        self._interval = timedelta(seconds=interval_seconds)
        self._run = run
        self._client_factory = client_factory
        self._clock = clock
        self._last_attempt: datetime | None = None  # 이 프로세스에서 handle을 시작한 시각

    def poll(self, limit: int | None) -> list[str]:
        """차례면 [SUBJECT_ID], 아니면 []. limit은 1 이상이면 결과에 영향이 없다."""
        with psycopg.connect(self._database_url, autocommit=True) as conn:
            return [SUBJECT_ID] if self._due(conn) else []

    def handle(self, subject_id: str) -> None:
        if subject_id != SUBJECT_ID:
            return
        with psycopg.connect(self._database_url, autocommit=True) as conn:
            if not self._due(conn):
                return  # 멱등: 이미 시도했다
            self._last_attempt = self._clock()
            made = collect_and_hypothesize(
                conn,
                self._settings,
                self._intel_settings,
                run=self._run,
                client_factory=self._client_factory,
                clock=self._clock,
                out=logger.info,
            )
        logger.info(format_hypothesize(made, self._settings.attack_version))

    def _due(self, conn: psycopg.Connection) -> bool:
        now = self._clock()
        if self._last_attempt is not None and now - self._last_attempt < self._interval:
            return False  # DB를 읽지 않아도 된다
        last = store.last_attempt_started_at(conn, TASK)
        return last is None or now - last >= self._interval


def read_generate_interval(l3: dict[str, Any]) -> float:
    """[l3.hunt] generate_interval_seconds. 생성 워커만 읽는다(HuntSettings에는 없다)."""
    hunt = l3.get("hunt")
    value = hunt.get("generate_interval_seconds") if isinstance(hunt, dict) else None
    if isinstance(value, bool) or not isinstance(value, int | float) or value <= 0:
        raise ConfigError("l3.hunt.generate_interval_seconds는 0보다 큰 수여야 한다")
    return float(value)


def build_worker(config: dict[str, Any]) -> HuntGenerator:
    """실행기 등록 함수(#215). config는 설정 전체이고 [l3]만 읽는다. DB에는 접속하지 않는다."""
    database_url = database_url_from_env()
    l3 = config.get("l3", {})
    settings = read_hunt_settings(l3)
    intel_settings = intel.read_settings(l3) if settings.collect_before else None
    return HuntGenerator(
        database_url,
        settings,
        intel_settings,
        interval_seconds=read_generate_interval(l3),
    )
