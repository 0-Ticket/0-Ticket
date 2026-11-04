"""설정의 조회 대상을 차례로 수집한다.

대상마다 체크포인트를 읽고, 페이지마다 RawRecord를 만들어 원본과 다음 위치를 한 트랜잭션으로
저장한다(store.save_page). 첫 실패에서 그 대상의 실행을 멈춘다. 같은 실행 안에서 다시 시도하거나
실패한 페이지를 건너뛰지 않는다. 체크포인트는 마지막 성공 페이지에 남아 다음 실행이 거기서
다시 조회한다.
한 대상이 실패해도 다음 대상은 계속한다.
"""

import sys
import time
from collections.abc import Callable
from contextlib import closing
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
import psycopg

from soc.contracts import ContractError, to_epoch_ms
from soc.ids import new_id
from soc.ingest import elk, store
from soc.ingest.config import Settings, Source
from soc.ingest.errors import IngestError


@dataclass
class SourceResult:
    name: str
    pages: int = 0
    inserted: int = 0
    failure: str | None = None


def run(
    settings: Settings,
    conn: psycopg.Connection,
    client: httpx.Client,
    *,
    clock: Callable[[], float] = time.monotonic,
) -> list[SourceResult]:
    """설정 순서대로 수집한다. conn은 autocommit 연결이다(트랜잭션은 store가 연다)."""
    return [_run_source(settings, source, conn, client, clock) for source in settings.sources]


def _run_source(
    settings: Settings,
    source: Source,
    conn: psycopg.Connection,
    client: httpx.Client,
    clock: Callable[[], float],
) -> SourceResult:
    result = SourceResult(name=source.name)
    try:
        checkpoint = store.load_checkpoint(conn, settings.siem_profile, source.kind, source.key)
        # 체크포인트가 없거나 cursor가 비어 있으면(첫 페이지부터 실패한 기록) 처음부터 조회한다
        start_ms = None if checkpoint is None else checkpoint["cursor"].get("time_ms")
        with closing(elk.iter_pages(client, settings, source, start_ms, clock=clock)) as pages:
            for hits in pages:
                fetched_at = _now_ms()
                records = [_raw_record(settings, source, hit, fetched_at) for hit in hits]
                next_checkpoint = {
                    "siem_profile": settings.siem_profile,
                    "source_kind": source.kind,
                    "source_key": source.key,
                    # 마지막 hit의 첫 정렬 값이 time_field 시각(epoch ms)이다
                    "cursor": {"time_ms": hits[-1]["sort"][0]},
                    "updated_at": fetched_at,
                    "last_error": None,
                }
                result.inserted += store.save_page(conn, records, next_checkpoint)
                result.pages += 1
    except IngestError as exc:
        result.failure = exc.kind
    except ContractError:
        result.failure = "contract_rejected"
    except psycopg.Error:
        result.failure = "db_error"

    if result.failure is not None:
        # 대상 이름과 종류 코드만 쓴다. 응답 본문, 원본, 주소, 인증 값은 쓰지 않는다.
        print(f"{result.name}: 실패 {result.failure}", file=sys.stderr)
        try:
            store.record_failure(
                conn, settings.siem_profile, source.kind, source.key, result.failure, _now_ms()
            )
        except psycopg.Error:
            # 실패 기록은 덤이다. DB가 안 되면 위 stderr 줄이 남는다.
            pass
    return result


def _raw_record(
    settings: Settings, source: Source, hit: dict[str, Any], fetched_at: int
) -> dict[str, Any]:
    return {
        "id": new_id("raw"),
        "kind": source.kind,
        "siem_profile": settings.siem_profile,
        "siem_ref": f"{hit['_index']}/{hit['_id']}",
        "fetched_at": fetched_at,
        "original": hit,
    }


def _now_ms() -> int:
    return to_epoch_ms(datetime.now(UTC))


def format_results(results: list[SourceResult]) -> list[str]:
    """대상마다 한 줄. 건수와 실패 종류만 쓴다."""
    return [
        f"{r.name}: 페이지 {r.pages}, 새로 저장 {r.inserted}, 실패 {r.failure or '없음'}"
        for r in results
    ]


def exit_code(results: list[SourceResult]) -> int:
    return 1 if any(r.failure for r in results) else 0
