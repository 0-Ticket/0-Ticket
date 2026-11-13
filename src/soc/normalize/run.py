"""W02 pending 원본과 W03 failed 원본을 한 묶음씩 정규화한다.

W02는 새 원본에 pending 상태를 만든 뒤 pending만 고르고, W03 재시도는 failed만 고른다.
한 건이 실패해도 나머지는 계속 처리한다.
"""

import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

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
    escaped = escape_unstorable(mapped.row)
    validate_ocsf(escaped["ocsf"])
    assets = lookup_assets(conn, escaped["entities"], settings.asset_statement_timeout_ms)
    row = {**escaped, "assets": assets}
    validate_contract(mapped.kind, row)
    return save_success(conn, owner, raw.id, mapped.kind, row)


# NUL과 짝 없는 서로게이트(U+D800..U+DFFF). jsonb는 NUL을, UTF-8은 서로게이트를 받지 않는다
_UNSTORABLE = re.compile("[\x00\ud800-\udfff]")


class EscapeCollisionError(NormalizeError):
    """같은 dict 안에서 서로 다른 두 키가 이스케이프 뒤 같은 키가 됐다.

    하나가 말없이 덮어쓰이지 않도록 원본을 실패(escape_collision)로 기록한다.
    """

    def __init__(self) -> None:
        """실패 코드 escape_collision을 가진 예외를 만든다."""
        super().__init__("escape_collision")


def escape_unstorable(value: Any) -> Any:
    """값 안의 NUL과 짝 없는 서로게이트를 6글자 이스케이프로 바꾼 새 값을 돌려준다(D-049).

    NUL은 \\u0000, 서로게이트는 \\udXXX(소문자 16진수) 6글자가 된다. jsonb는 NUL을 받지 않고
    서로게이트는 UTF-8로 쓸 수 없다. 저장 전에 문자열 값과 dict 키 모두에 적용한다.
    dict·list는 안쪽까지 재귀로 바꾸고, 다른 타입은 그대로 둔다. 입력은 바꾸지 않는다.
    이 치환 결과는 원본에 글자로 있던 \\u0000과 구분되지 않는다.
    한 dict 안에서 두 키가 이스케이프 뒤 같아지면 값을 덮어쓰지 않고 EscapeCollisionError를 낸다.

    Args:
        value: 정규화 결과 행(또는 그 일부).

    Returns:
        같은 모양의 새 값.

    Raises:
        EscapeCollisionError: 한 dict 안에서 이스케이프 뒤 키가 겹쳤다.
    """
    if isinstance(value, str):
        return _UNSTORABLE.sub(lambda match: f"\\u{ord(match.group()):04x}", value)
    if isinstance(value, dict):
        escaped: dict[Any, Any] = {}
        for key, item in value.items():
            new_key = escape_unstorable(key)
            if new_key in escaped:
                raise EscapeCollisionError
            escaped[new_key] = escape_unstorable(item)
        return escaped
    if isinstance(value, list):
        return [escape_unstorable(item) for item in value]
    return value


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
