"""파이프의 정규화·Ticket 생성 워커(#316). 기존 한 번 실행 명령의 run()을 그대로 부른다.

두 워커는 "건"이 아니라 "배치" 단위다. poll은 처리할 것이 있을 때만 고정 토큰 하나를 돌려주고
(없으면 빈 목록이라 실행기 라운드 로그도 남지 않는다), handle이 run()을 한 번 부른다.
연결은 poll·handle마다 열고 닫는다. 로그에는 건수와 실패 코드만 남긴다.
"""

import logging
import os
import uuid
from typing import Any

import psycopg

from soc.api.db import DATABASE_URL_ENV
from soc.l1.ticketing import _CANDIDATE_IDS
from soc.l1.ticketing import run as ticketing_run
from soc.normalize.config import Settings, load_settings
from soc.normalize.run import run as normalize_run

logger = logging.getLogger("soc.pipeline")

TOKEN = "batch"

# normalize.store의 _ADD_STATUS_ROWS·_LEASE가 집는 조건과 같다(어긋나지 않게 db 테스트로 묶는다)
_NORMALIZE_PENDING = """
SELECT EXISTS (
    SELECT 1 FROM raw_records r
    WHERE NOT EXISTS (SELECT 1 FROM normalize_status s WHERE s.raw_id = r.id)
) OR EXISTS (
    SELECT 1 FROM normalize_status
    WHERE status = 'pending' AND (lease_expires_at IS NULL OR lease_expires_at < now())
)
"""
_TICKET_PENDING = f"SELECT EXISTS (SELECT 1 FROM ({_CANDIDATE_IDS}) AS candidates)"  # noqa: S608


def _any(database_url: str, query: str) -> list[str]:
    with psycopg.connect(database_url, autocommit=True) as conn:
        row = conn.execute(query).fetchone()
    return [TOKEN] if row is not None and row[0] else []


class NormalizeWorker:
    """pending 원본을 한 배치씩 정규화한다. failed 재시도는 하지 않는다."""

    stage = "normalize"
    name = "normalize"

    def __init__(self, database_url: str, settings: Settings) -> None:
        self._database_url = database_url
        self._settings = settings

    def poll(self, limit: int) -> list[str]:
        return _any(self._database_url, _NORMALIZE_PENDING)

    def handle(self, subject_id: str) -> None:
        with psycopg.connect(
            self._database_url,
            autocommit=True,
            connect_timeout=self._settings.connect_timeout_seconds,
        ) as conn:
            result = normalize_run(self._settings, conn, uuid.uuid4().hex)
        logger.info(
            "normalize claimed=%d succeeded=%d failed=%d lease_lost=%d",
            result.claimed,
            result.succeeded,
            result.failed,
            result.lease_lost,
        )
        if result.failed:
            codes = " ".join(f"{k}={v}" for k, v in sorted(result.failures.items()))
            logger.warning("normalize 실패 %s", codes)


class TicketingWorker:
    """정규화된 Alert를 현재 정책으로 분기해 Ticket을 만든다."""

    stage = "ticketing"
    name = "ticketing"

    def __init__(self, database_url: str) -> None:
        self._database_url = database_url

    def poll(self, limit: int) -> list[str]:
        return _any(self._database_url, _TICKET_PENDING)

    def handle(self, subject_id: str) -> None:
        with psycopg.connect(self._database_url, autocommit=True) as conn:
            result = ticketing_run(conn)
        logger.info(
            "ticketing candidates=%d created=%d pending=%d skipped=%d failed=%d",
            result.candidates,
            result.created,
            result.pending,
            result.skipped,
            result.failed,
        )
        if result.failed:
            codes = " ".join(f"{k}={v}" for k, v in sorted(result.failures.items()))
            logger.warning("ticketing 실패 %s", codes)


def _database_url() -> str:
    url = os.environ.get(DATABASE_URL_ENV)
    if not url:
        raise ValueError(f"{DATABASE_URL_ENV}가 필요하다")
    return url


def build_normalize_worker(config: dict[str, Any]) -> NormalizeWorker:
    return NormalizeWorker(_database_url(), load_settings())


def build_ticketing_worker(config: dict[str, Any]) -> TicketingWorker:
    return TicketingWorker(_database_url())
