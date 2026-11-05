"""W02 pending 원본과 W03 failed 원본을 한 묶음씩 정규화한다.

W02는 새 원본에 pending 상태를 만든 뒤 pending만 고르고, W03 재시도는 failed만 고른다.
한 건이 실패해도 나머지는 계속 처리한다.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

import psycopg

from soc.asset_lookup import AssetLookupError, lookup_assets
from soc.contracts import ContractError, validate_contract
from soc.normalize.config import Settings
from soc.normalize.errors import NormalizeError
from soc.normalize.mapping import RawRow, normalize
from soc.normalize.ocsf_schema import validate_ocsf
from soc.normalize.store import claim_failed_batch, claim_pending_batch, save_failure, save_success


@dataclass
class RunResult:
    """한 번 실행의 결과.

    Attributes:
        claimed: 이번 실행이 임대한 원본 수.
        succeeded: 결과를 저장한 건수.
        failed: 실패로 기록한 건수.
        lease_lost: 임대가 만료되어 결과나 실패를 기록하지 못한 건수.
        failures: 실패 코드별 건수.
    """

    claimed: int = 0
    succeeded: int = 0
    failed: int = 0
    lease_lost: int = 0
    failures: dict[str, int] = field(default_factory=dict)


def run(settings: Settings, conn: psycopg.Connection, owner: str) -> RunResult:
    """pending 원본 한 묶음을 정규화한다.

    Args:
        settings: 정규화 설정.
        conn: DB 연결(autocommit). 결과 저장과 자산 조회에 함께 쓴다.
        owner: 이번 실행을 가리키는 임대 소유자 값.
    """
    return _run_batch(settings, conn, owner, claim_pending_batch)


def run_failed(settings: Settings, conn: psycopg.Connection, owner: str) -> RunResult:
    """failed 원본 한 묶음을 다시 정규화한다.

    Args:
        settings: 정규화 설정.
        conn: DB 연결(autocommit). 결과 저장과 자산 조회에 함께 쓴다.
        owner: 이번 실행을 가리키는 임대 소유자 값.
    """
    return _run_batch(settings, conn, owner, claim_failed_batch)


def _run_batch(
    settings: Settings,
    conn: psycopg.Connection,
    owner: str,
    claim: Callable[[psycopg.Connection, str, int, int], list[RawRow]],
) -> RunResult:
    """한 상태 종류의 원본을 맡아 건마다 변환·검증·자산 조회·저장한다."""
    result = RunResult()
    for raw in claim(conn, owner, settings.batch_size, settings.lease_seconds):
        result.claimed += 1
        try:
            saved = _normalize_and_save(settings, conn, owner, raw)
        except (NormalizeError, AssetLookupError, ContractError, psycopg.Error) as error:
            code = _failure_code(error)
            if save_failure(conn, owner, raw.id, code):
                result.failed += 1
                result.failures[code] = result.failures.get(code, 0) + 1
            else:
                result.lease_lost += 1
        else:
            if saved:
                result.succeeded += 1
            else:
                result.lease_lost += 1
    return result


def exit_code(result: RunResult) -> int:
    """실패가 하나라도 있으면 1, 없으면 0.

    Args:
        result: run의 결과.
    """
    return 1 if result.failed else 0


def _normalize_and_save(
    settings: Settings, conn: psycopg.Connection, owner: str, raw: RawRow
) -> bool:
    """원본 한 건을 변환·검증하고 자산을 붙여 저장한다.

    Args:
        settings: 정규화 설정.
        conn: DB 연결.
        owner: 임대 소유자 값.
        raw: 처리할 원본.

    Returns:
        저장했으면 True, 임대를 잃어 저장하지 않았으면 False.
    """
    mapped = normalize(raw)
    validate_ocsf(mapped.row["ocsf"])
    assets = lookup_assets(conn, mapped.row["entities"], settings.asset_statement_timeout_ms)
    row = {**mapped.row, "assets": assets}
    validate_contract(mapped.kind, row)
    return save_success(conn, owner, raw.id, mapped.kind, row)


def _failure_code(error: Exception) -> str:
    """예외를 실패 코드로 바꾼다. 예외 메시지는 쓰지 않는다.

    Args:
        error: _normalize_and_save가 던진 예외.
    """
    if isinstance(error, NormalizeError | AssetLookupError):
        return error.code
    if isinstance(error, ContractError):
        return "validation_failed"
    return "db_error"
