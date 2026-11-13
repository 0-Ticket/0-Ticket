"""설정의 조회 대상을 차례로 수집한다.

조회 시작 시각은 체크포인트·--since·기본 범위로 정한다(resolve_start_ms, D-055).

대상마다 체크포인트를 읽고, 정상 RawRecord·격리 행·필요한 다음 체크포인트를 페이지 단위 트랜잭션으로
함께 저장한다(store.save_page). 일시적인 요청 실패는 요청마다 최대 3회 시도한다.
정렬 값이 잘못된 페이지는 같은 경계를 유지해 최대 3회 다시 읽는다.
그 밖의 실패는 해당 대상 실행을 멈추며 실패한 페이지를 건너뛰지 않는다.
체크포인트는 마지막 커밋 페이지에 남아 다음 실행에서 거기서 다시 조회한다.
한 대상이 실패해도 다음 대상은 계속한다.
대상마다 실행이 끝나면(성공·실패 모두) 실행 이력 한 행을 남긴다(store.record_run).
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

from soc.contracts import ContractError, to_epoch_ms, validate_contract
from soc.ids import new_id, siem_ref_key
from soc.ingest import elk, store
from soc.ingest.config import Settings, Source
from soc.ingest.errors import IngestError
from soc.ingest.quarantine import (
    contains_nonfinite,
    exceeds_depth,
    quarantine_key,
    serialize_original,
    valid_sort_value,
)


@dataclass
class SourceResult:
    """조회 대상 하나의 실행 결과. 출력 한 줄과 종료 코드를 만드는 데 쓴다.

    필드:
        name: 대상 이름(Source.name, "kind:key" 형식).
        started_at: 이 대상의 실행을 시작한 시각(epoch ms). 실행 이력에 쓴다.
        pages: 저장까지 끝난 페이지 수. 빈 페이지는 세지 않는다.
        inserted: 이번 실행에서 새로 저장한 원본 수. 이미 있던 문서는 세지 않는다.
        quarantined: 이번 실행에서 새로 저장한 격리 행 수. 중복은 세지 않는다.
        failure: 실패 종류 코드. 성공이면 None.
        fetched: 저장까지 끝난 페이지의 hit 수. 건너뜀은 fetched - inserted - quarantined다.
        start_ms: 이번에 조회를 시작한 시각(epoch ms). 시작 전에 실패했으면 None.
        last_ms: 가져온 문서 중 가장 늦은 시각(epoch ms). 한 건도 없으면 None.
        finished_at: 대상 실행을 마친 시각(epoch ms). 소요 시간 계산에 쓴다.
        reason: 실패 이유 문구(원인별 안내). 키·주소·계정 값은 담지 않는다. 성공이면 None.
    """

    name: str
    started_at: int
    pages: int = 0
    inserted: int = 0
    quarantined: int = 0
    failure: str | None = None
    fetched: int = 0
    start_ms: int | None = None
    last_ms: int | None = None
    finished_at: int | None = None
    reason: str | None = None


def run(
    settings: Settings,
    conn: psycopg.Connection,
    client: httpx.Client,
    *,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    since_ms: int | None = None,
    now_ms: int | None = None,
) -> list[SourceResult]:
    """설정의 조회 대상을 순서대로 수집한다. 한 대상이 실패해도 다음 대상은 계속한다.

    인자:
        settings: read_settings()가 만든 설정.
        conn: autocommit 연결. 트랜잭션은 store.save_page가 연다.
        client: ELK HTTP 클라이언트(elk.make_client로 만든다).
        clock: 응답 마감 시간을 재는 함수. 테스트에서 바꿔 끼운다.
        since_ms: --since로 정한 시각(epoch ms). 시작 시각 규칙은 resolve_start_ms에 있다.
        now_ms: 기본 범위의 기준 "지금"(epoch ms). None이면 시스템 시계다.

    반환:
        대상마다 하나의 SourceResult. 설정 순서와 같다.
    """
    if now_ms is None:
        now_ms = int(time.time() * 1000)
    return [
        _run_source(settings, source, conn, client, clock, sleep, since_ms, now_ms)
        for source in settings.sources
    ]


def resolve_start_ms(
    checkpoint_ms: int | None, since_ms: int | None, settings: Settings, now_ms: int
) -> int:
    """조회를 시작할 시각(epoch ms)을 정한다(D-055).

    체크포인트가 없으면 --since, 그것도 없으면 지금 - initial_lookback_seconds다.
    있으면 체크포인트 - overlap_seconds이고, --since가 더 이르면 그것을 쓴다. --since가 더 늦으면
    무시한다(사이 구간을 건너뛰지 않으려고).

    인자:
        checkpoint_ms: 저장된 체크포인트 시각. 없으면 None.
        since_ms: --since 시각. 없으면 None.
        settings: initial_lookback_seconds, overlap_seconds.
        now_ms: 기준 "지금".
    """
    if checkpoint_ms is None:
        if since_ms is not None:
            return since_ms
        return max(now_ms - settings.initial_lookback_seconds * 1000, 0)
    start = max(checkpoint_ms - settings.overlap_seconds * 1000, 0)
    return start if since_ms is None else min(since_ms, start)


def _run_source(
    settings: Settings,
    source: Source,
    conn: psycopg.Connection,
    client: httpx.Client,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    since_ms: int | None,
    now_ms: int,
) -> SourceResult:
    """대상 하나를 수집한다. 첫 실패에서 멈추고, 끝나면 실행 이력을 남긴다.

    인자:
        settings: 설정(siem_profile 등).
        source: 이번에 수집할 대상.
        conn: autocommit 연결.
        client: ELK HTTP 클라이언트.
        clock: 응답 마감 시간을 재는 함수.
        since_ms: --since 시각. 없으면 None.
        now_ms: 기본 범위의 기준 "지금".

    반환:
        이 대상의 SourceResult. 실패하면 failure에 종류 코드가 있다.

    부수 효과:
        실패하면 stderr에 "대상: 실패 종류" 한 줄을 쓴다. 성공·실패(0건 포함) 모두 실행 이력 한 행
        (outcome은 "ok" 또는 실패 종류 코드)을 쌓는다. 이력 쓰기가 DB 오류로 실패하면 무시한다.
    """
    result = SourceResult(name=source.name, started_at=_now_ms())
    try:
        checkpoint = store.load_checkpoint(conn, settings.siem_profile, source.kind, source.key)
        # 체크포인트가 없거나 cursor가 비어 있으면(0100 시기 첫 페이지 실패 행) 체크포인트가 없는
        # 것으로 본다. 시작 시각은 resolve_start_ms가 정한다.
        start_ms = resolve_start_ms(_checkpoint_time(checkpoint), since_ms, settings, now_ms)
        result.start_ms = start_ms
        with closing(
            elk.iter_pages(client, settings, source, start_ms, clock=clock, sleep=sleep)
        ) as pages:
            for hits in pages:
                fetched_at = _now_ms()
                records: list[dict[str, Any]] = []
                quarantines: list[dict[str, Any]] = []
                for hit in hits:
                    reason = _quarantine_reason(hit)
                    if reason is None:
                        record = _raw_record(settings, source, hit, fetched_at)
                        try:
                            validate_contract("raw_record", record)
                        except ContractError:
                            reason = "contract_rejected"
                        else:
                            records.append(record)
                    if reason is not None:
                        quarantines.append(
                            _quarantine_record(settings, source, hit, reason, fetched_at)
                        )

                next_checkpoint = None
                if valid_sort_value(hits[-1]):
                    next_checkpoint = {
                        "siem_profile": settings.siem_profile,
                        "source_kind": source.kind,
                        "source_key": source.key,
                        # 마지막 hit의 첫 정렬 값이 time_field 시각(epoch ms)이다
                        "cursor": {"time_ms": hits[-1]["sort"][0]},
                        "updated_at": fetched_at,
                    }
                inserted, quarantined = store.save_page(
                    conn, records, next_checkpoint, quarantines=quarantines
                )
                result.inserted += inserted
                result.quarantined += quarantined
                result.pages += 1
                result.fetched += len(hits)
                if next_checkpoint is not None:
                    last = next_checkpoint["cursor"]["time_ms"]
                    result.last_ms = last if result.last_ms is None else max(result.last_ms, last)
    except IngestError as exc:
        result.failure = exc.kind
    except ContractError:
        result.failure = "contract_rejected"
    except psycopg.Error:
        result.failure = "db_error"

    if result.failure is not None:
        # 대상 이름과 종류 코드만 쓴다. 응답 본문, 원본, 주소, 인증 값은 쓰지 않는다.
        print(f"{result.name}: 실패 {result.failure}", file=sys.stderr)
        result.reason = failure_reason(result.failure, settings)
    # 시계가 뒤로 가도 이력 계약(finished_at >= started_at)을 어기지 않게 한다
    result.finished_at = max(_now_ms(), result.started_at)
    try:
        store.record_run(
            conn,
            {
                "siem_profile": settings.siem_profile,
                "source_kind": source.kind,
                "source_key": source.key,
                "started_at": result.started_at,
                "finished_at": result.finished_at,
                "outcome": result.failure or "ok",
                "pages": result.pages,
                "inserted": result.inserted,
                "quarantined": result.quarantined,
            },
        )
    except psycopg.Error:
        # 이력은 덤이다. 원본·체크포인트는 이미 커밋됐고, 실패 종류는 위 stderr 줄에 남는다.
        pass
    return result


def _raw_record(
    settings: Settings, source: Source, hit: dict[str, Any], fetched_at: int
) -> dict[str, Any]:
    """ELK hit 하나를 RawRecord 계약 모양의 dict로 만든다.

    인자:
        settings: siem_profile을 얻는 데 쓴다.
        source: kind를 얻는 데 쓴다.
        hit: ELK 검색 응답의 hit 객체. 바꾸지 않고 JSON 글자로 original_text에 넣는다.
        fetched_at: 가져온 시각(epoch ms).

    반환:
        id(new_id("raw")), kind, siem_profile, siem_ref, fetched_at, original_text를 담은 dict.
        original_text는 json.dumps(hit, ensure_ascii=True)다. NUL·짝 없는 서로게이트는 이스케이프
        글자가 되어 PostgreSQL text에 들어가고, siem_ref는 같은 규칙으로 JSON 문자열 이스케이프한
        값에서 양쪽 따옴표를 뺀 것이다(D-049, soc.ids.siem_ref_key).
    """
    return {
        "id": new_id("raw"),
        "kind": source.kind,
        "siem_profile": settings.siem_profile,
        "siem_ref": siem_ref_key(f"{hit['_index']}/{hit['_id']}"),
        "fetched_at": fetched_at,
        "original_text": serialize_original(hit),
    }


def _checkpoint_time(checkpoint: dict[str, Any] | None) -> int | None:
    """체크포인트 시각을 확인한다. 빈 커서는 처음부터 시작하는 예전 행이다."""
    if checkpoint is None:
        return None
    cursor = checkpoint["cursor"]
    if not isinstance(cursor, dict):
        raise IngestError("checkpoint_cursor")
    if not cursor:
        return None
    if "time_ms" not in cursor:
        raise IngestError("checkpoint_cursor")
    time_ms = cursor["time_ms"]
    if isinstance(time_ms, bool) or not isinstance(time_ms, int) or time_ms < 0:
        raise IngestError("checkpoint_cursor")
    return time_ms


def _quarantine_reason(hit: Any) -> str | None:
    """hit 하나의 저장 적합성을 계획에 정한 순서대로 분류한다."""
    if not isinstance(hit, dict):
        return "hit_ref"
    if not valid_sort_value(hit):
        return "sort_value"
    if not _valid_identifier(hit.get("_index")) or not _valid_identifier(hit.get("_id")):
        return "hit_ref"
    if exceeds_depth(hit):
        return "depth_exceeded"
    if contains_nonfinite(hit):
        return "non_finite"
    return None


def _valid_identifier(value: Any) -> bool:
    """SIEM의 _index·_id가 비어 있지 않은 문자열인지 확인한다."""
    return isinstance(value, str) and bool(value)


def _quarantine_record(
    settings: Settings, source: Source, hit: Any, reason: str, seen_at: int
) -> dict[str, Any]:
    """격리 행의 계약 필드를 만든다. 전체 hit는 original_text에 보존한다."""
    return {
        "siem_profile": settings.siem_profile,
        "source_kind": source.kind,
        "source_key": source.key,
        "siem_ref": quarantine_key(source.kind, source.key, hit),
        "reason_code": reason,
        "original_text": serialize_original(hit),
        "seen_at": seen_at,
    }


def _now_ms() -> int:
    """현재 UTC 시각을 epoch 밀리초로 돌려준다."""
    return to_epoch_ms(datetime.now(UTC))


# 실패 종류별 이유 문구. 환경변수 이름과 설정 키 이름만 내고 값(주소·키·계정)은 내지 않는다.
_REASONS = {
    "auth": "ELK 인증에 실패했다. API 키 환경변수 {api_key_env}를 확인한다",
    "tls": "ELK 인증서를 검증하지 못했다. [ingest] ca_cert_path 설정을 확인한다",
    "network": "ELK에 연결하지 못했다. 네트워크와 주소 환경변수 {url_env}를 확인한다",
    "timeout": "ELK 응답이 제한 시간을 넘겼다",
    "http_status": "ELK가 오류 응답을 줬다",
    "too_large": "ELK 응답이 크기 상한을 넘었다",
    "response_shape": "ELK 응답 모양이 기대와 다르다",
    "sort_value": "ELK 문서의 정렬 값이 유효하지 않다",
    "checkpoint_cursor": "저장된 체크포인트 값이 유효하지 않다",
    "contract_rejected": "저장하려는 원본이 계약에 맞지 않는다",
    "db_error": "DB 저장에 실패했다. DATABASE_URL과 마이그레이션을 확인한다",
}


def failure_reason(kind: str, settings: Settings) -> str:
    """실패 종류 코드의 이유 문구를 돌려준다. 값(주소·키·계정)은 담지 않는다."""
    return _REASONS[kind].format(url_env=settings.url_env, api_key_env=settings.api_key_env)


def _iso(ms: int | None) -> str:
    """epoch ms를 UTC ISO 8601(초 단위, Z)로 쓴다. None이면 "-"."""
    if ms is None:
        return "-"
    return datetime.fromtimestamp(ms / 1000, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_results(results: list[SourceResult]) -> list[str]:
    """대상마다 요약 한 줄을 만든다. 건수·구간·소요 시간·실패 종류와 이유만 쓴다.

    인자:
        results: run()이 돌려준 결과 목록.

    반환:
        "이름: 구간 시작 ~ 끝, 가져옴 n, 새로 저장 n, 건너뜀 n, 격리 n, 페이지 n, s초, 실패 ..."
        형식의 줄 목록. 실패하면 줄 끝에 이유가 붙는다.
    """
    lines = []
    for r in results:
        elapsed = ((r.finished_at or r.started_at) - r.started_at) / 1000
        skipped = r.fetched - r.inserted - r.quarantined
        line = (
            f"{r.name}: 구간 {_iso(r.start_ms)} ~ {_iso(r.last_ms)}, 가져옴 {r.fetched}, "
            f"새로 저장 {r.inserted}, 건너뜀 {skipped}, 격리 {r.quarantined}, "
            f"페이지 {r.pages}, {elapsed:.1f}초, 실패 {r.failure or '없음'}"
        )
        lines.append(f"{line} - {r.reason}" if r.reason else line)
    return lines


def format_footer(results: list[SourceResult]) -> list[str]:
    """요약 끝줄: 전체 소요 시간과 다음에 볼 곳. 상태 조회 명령이 생기면 이 안내를 바꾼다."""
    started = min((r.started_at for r in results), default=0)
    finished = max((r.finished_at or r.started_at for r in results), default=started)
    return [
        f"전체 소요 {(finished - started) / 1000:.1f}초",
        "결과 확인: DB의 ingest_runs 테이블(상태 조회 명령은 아직 없다)",
    ]


def exit_code(results: list[SourceResult]) -> int:
    """인자 results 중 실패가 하나라도 있으면 1, 아니면 0을 돌려준다."""
    return 1 if any(r.failure for r in results) else 0
