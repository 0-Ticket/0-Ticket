"""정규화된 Alert를 현재 정책으로 한 번 분기하고 Ticket을 저장한다(#246)."""

import os
import sys
import tomllib
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from soc.api.db import DATABASE_URL_ENV
from soc.contracts import ContractError, to_datetime, to_epoch_ms, validate_contract
from soc.ids import new_id
from soc.ticketing import (
    ConfigError,
    TicketingPolicy,
    load_policy,
    read_active_policy,
)

_CANDIDATE_IDS = """
SELECT a.id
FROM normalize_status AS s
JOIN alerts AS a ON a.id = s.result_id
WHERE s.status = 'succeeded'
  AND s.result_kind = 'alert'
  AND a.triage IS NULL
  AND NOT EXISTS (
      SELECT 1 FROM tickets AS t WHERE t.alert_ids @> ARRAY[a.id]::text[]
  )
ORDER BY a.time, a.id
"""

_LOCK_ALERT = """
SELECT a.id, a.rule_id, a.entities
FROM alerts AS a
JOIN normalize_status AS s ON s.result_id = a.id
WHERE a.id = %s
  AND s.status = 'succeeded'
  AND s.result_kind = 'alert'
  AND a.triage IS NULL
FOR UPDATE OF a SKIP LOCKED
"""

_TICKET_COLUMNS = (
    "id",
    "origin",
    "status",
    "alert_ids",
    "hunt_id",
    "entities",
    "verdict",
    "created_at",
    "updated_at",
    "details",
)
_TICKET_TIME_COLUMNS = frozenset({"created_at", "updated_at"})
_TICKET_JSON_COLUMNS = frozenset({"entities", "verdict", "details"})
_TICKET_UNIQUE_INDEX = "tickets_auto_scenario_l1_alert_uidx"


@dataclass
class RunResult:
    """한 번 실행한 Alert 분기 건수."""

    candidates: int = 0
    created: int = 0
    pending: int = 0
    skipped: int = 0
    failed: int = 0
    failures: Counter[str] = field(default_factory=Counter)


@dataclass(frozen=True)
class AlertOutcome:
    """Alert 분기 결과. 기존 Ticket은 변경 없이 호출자에게 돌려준다."""

    status: str
    ticket: dict[str, Any] | None = None


def _utcnow_ms() -> int:
    return to_epoch_ms(datetime.now(UTC))


def run(
    conn: psycopg.Connection,
    fallback: TicketingPolicy | None = None,
    *,
    clock: Callable[[], int] = _utcnow_ms,
) -> RunResult:
    """대상 ID를 한 번 모은 뒤 각 Alert를 최대 한 번 처리한다.

    conn은 Alert별 트랜잭션이 서로 독립되도록 autocommit 연결이어야 한다.
    Alert 잠금과 정책 스냅샷, 결과 저장은 한 트랜잭션 안에서 일어난다. 실패한 건은 롤백되며
    다음 명령 실행에서 다시 선택된다.
    """
    if not conn.autocommit:
        raise ValueError("W04 실행에는 autocommit DB 연결이 필요하다")
    result = RunResult()
    ids = [row[0] for row in conn.execute(_CANDIDATE_IDS).fetchall()]
    result.candidates = len(ids)
    if ids and fallback is None and read_active_policy(conn) is None:
        # 활성 DB 정책이 있을 때는 TOML을 읽지 않아 DB 우선순위를 보장한다.
        fallback = load_policy()
    for alert_id in ids:
        try:
            outcome = _process_alert(conn, alert_id, fallback, clock())
        except ContractError:
            result.failed += 1
            result.failures["contract_error"] += 1
        except (ConfigError, OSError, tomllib.TOMLDecodeError):
            result.failed += 1
            result.failures["policy_error"] += 1
        except psycopg.Error:
            result.failed += 1
            result.failures["db_error"] += 1
        except Exception:
            # 예외 메시지에는 DB 값이나 원문 문자열이 섞일 수 있어 종류별 코드만 남긴다.
            result.failed += 1
            result.failures["internal_error"] += 1
        else:
            if outcome.status == "created":
                result.created += 1
            elif outcome.status == "pending":
                result.pending += 1
            else:
                result.skipped += 1
    return result


def exit_code(result: RunResult) -> int:
    return 1 if result.failed else 0


def _process_alert(
    conn: psycopg.Connection,
    alert_id: str,
    fallback: TicketingPolicy | None,
    now_ms: int,
) -> AlertOutcome:
    """Alert 하나를 잠근 상태에서 정책을 읽고 결과를 원자적으로 저장한다."""
    with conn.transaction():
        row = conn.execute(_LOCK_ALERT, (alert_id,)).fetchone()
        if row is None:
            return AlertOutcome("skipped")
        if isinstance(row, Mapping):
            alert = {"id": row["id"], "rule_id": row["rule_id"], "entities": row["entities"]}
        else:
            alert = dict(zip(("id", "rule_id", "entities"), row, strict=True))

        existing = _existing_ticket(conn, alert_id)
        if existing is not None:
            return AlertOutcome("existing", existing)

        policy = read_active_policy(conn)
        if policy is None:
            policy = fallback if fallback is not None else load_policy()
        if policy.mode == "auto" or alert["rule_id"] in policy.scenario_rule_ids:
            origin = "auto" if policy.mode == "auto" else "scenario"
            ticket = _make_ticket(alert, origin, now_ms)
            validate_contract("ticket", ticket)
            conflict_ticket = _insert_ticket(conn, ticket)
            # W04 유일성 인덱스의 충돌이면 기존 행을 그대로 사용한다.
            if conflict_ticket is not None:
                return AlertOutcome("existing", conflict_ticket)
            return AlertOutcome("created", ticket)

        conn.execute(
            "UPDATE alerts SET triage = %s WHERE id = %s",
            (Jsonb({"status": "pending", "verdict": None}), alert_id),
        )
        return AlertOutcome("pending")


def _make_ticket(alert: dict[str, Any], origin: str, now_ms: int) -> dict[str, Any]:
    return {
        "id": new_id("tkt"),
        "origin": origin,
        "status": "new",
        "alert_ids": [alert["id"]],
        "hunt_id": None,
        "entities": alert["entities"],
        "verdict": None,
        "created_at": now_ms,
        "updated_at": now_ms,
        "details": {},
    }


def _existing_ticket(
    conn: psycopg.Connection, alert_id: str, *, w04_only: bool = False
) -> dict[str, Any] | None:
    suffix = " AND origin IN ('auto', 'scenario', 'l1')" if w04_only else ""
    row = conn.execute(
        f"SELECT {', '.join(_TICKET_COLUMNS)} FROM tickets"
        f" WHERE alert_ids @> ARRAY[%s]::text[]{suffix} LIMIT 1",
        (alert_id,),
    ).fetchone()
    if row is None:
        return None
    if isinstance(row, Mapping):
        return dict(row)
    return dict(zip(_TICKET_COLUMNS, row, strict=True))


def _insert_ticket(conn: psycopg.Connection, ticket: dict[str, Any]) -> dict[str, Any] | None:
    """Ticket을 넣는다. Alert 유일성 충돌만 기존 Ticket 재사용으로 바꾼다."""
    query = sql.SQL("INSERT INTO tickets ({}) VALUES ({})").format(
        sql.SQL(", ").join(map(sql.Identifier, _TICKET_COLUMNS)),
        sql.SQL(", ").join(sql.Placeholder() * len(_TICKET_COLUMNS)),
    )
    values = [_db_value(column, ticket[column]) for column in _TICKET_COLUMNS]
    try:
        # 트랜잭션 안의 savepoint라면 실패 후 바깥 Alert 트랜잭션은 계속 쓸 수 있다.
        with conn.transaction():
            conn.execute(query, values)
    except psycopg.errors.UniqueViolation as exc:
        if exc.diag.constraint_name != _TICKET_UNIQUE_INDEX:
            raise
        existing = _existing_ticket(conn, ticket["alert_ids"][0], w04_only=True)
        if existing is None:
            raise
        return existing
    return None


def _db_value(column: str, value: Any) -> Any:
    if value is None:
        return None
    if column in _TICKET_TIME_COLUMNS:
        return to_datetime(value)
    if column in _TICKET_JSON_COLUMNS:
        return Jsonb(value)
    return value


def _format(result: RunResult) -> str:
    line = (
        f"candidates={result.candidates} created={result.created} pending={result.pending}"
        f" skipped={result.skipped} failed={result.failed}"
    )
    failures = " ".join(f"{code}={count}" for code, count in sorted(result.failures.items()))
    return f"{line} {failures}".rstrip()


def main() -> int:
    """정책 설정과 DB를 읽어 Ticket 분기를 한 번 실행한다."""
    database_url = os.environ.get(DATABASE_URL_ENV)
    if not database_url:
        print(f"환경변수 {DATABASE_URL_ENV}가 필요하다", file=sys.stderr)
        return 2
    try:
        with psycopg.connect(database_url, autocommit=True) as conn:
            result = run(conn)
    except (ConfigError, OSError, tomllib.TOMLDecodeError) as exc:
        print(f"설정 오류: {type(exc).__name__}", file=sys.stderr)
        return 2
    except psycopg.Error as exc:
        print(
            f"DB 오류({type(exc).__name__}). DATABASE_URL과 마이그레이션을 확인한다",
            file=sys.stderr,
        )
        return 1
    print(_format(result))
    return exit_code(result)


if __name__ == "__main__":
    sys.exit(main())
