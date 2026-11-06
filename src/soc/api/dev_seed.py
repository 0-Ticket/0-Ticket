"""개발 DB 전용: python -m soc.api.dev_seed --yes.

고정 ID 샘플을 한 트랜잭션으로 추가한다. 기존 행이 샘플과 다르면 전체를 되돌린다.
삭제·덮어쓰기·자동 마이그레이션은 하지 않는다. 실행기는 별도로 멈춘 개발 DB를 사용한다.
"""

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from soc.api.ui_read import times
from soc.contracts import to_datetime, validate_contract

SEED_PATH = Path(__file__).resolve().parents[3] / "tests/fixtures/api/ui_seed.json"
SEED_SOURCE = "dev-seed-ui"
CONTRACTS = {
    "raw_records": "raw_record",
    "normalize_status": None,
    "alerts": "alert",
    "events": "event",
    "hunts": "hunt",
    "tickets": "ticket",
    "incidents": "incident",
    "incident_artifacts": "incident_artifact",
    "incident_proposals": "incident_proposal",
    "cases": "case",
    "agent_logs": "agent_log",
}
TIMES = {
    "time",
    "created_at",
    "updated_at",
    "fetched_at",
    "verified_at",
    "started_at",
    "confirmed_at",
    "resolved_at",
    "last_attempt_at",
}
JSON_FIELDS = {
    "original",
    "ocsf",
    "assets",
    "triage",
    "timeline",
    "techniques",
    "entities",
    "details",
    "input",
    "output",
}


class SeedConflict(Exception):
    """기존 행이 시드와 다르다. ID·원문·DB 주소는 예외에 넣지 않는다."""


def load_seed() -> dict[str, list[dict[str, Any]]]:
    rows = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    if set(rows) != set(CONTRACTS):
        raise ValueError("시드 테이블 집합 오류")
    for table, records in rows.items():
        for row in records:
            contract = CONTRACTS[table]
            if contract:
                validate_contract(contract, row)
            if table == "raw_records" and row["siem_profile"] != SEED_SOURCE:
                raise ValueError("시드 프로필 오류")
            if "details" in row and (
                row["details"].get("seed_source") != SEED_SOURCE or "dev_seed" in row["details"]
            ):
                raise ValueError("시드 표시 오류")
    return rows


def _value(table: str, column: str, value: Any) -> Any:
    if value is None:
        return None
    if column in TIMES:
        return to_datetime(value)
    if column in JSON_FIELDS or (table == "tickets" and column == "verdict"):
        return Jsonb(value)
    return value


def seed(conn: psycopg.Connection) -> dict[str, int]:
    rows = load_seed()
    inserted = {table: 0 for table in CONTRACTS}
    with conn.transaction():
        # 동일 시드 명령의 동시 실행도 하나씩 확인하고 삽입한다.
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (266001,))
        with conn.cursor(row_factory=dict_row) as cur:
            for table, records in rows.items():
                for row in records:
                    key = "raw_id" if table == "normalize_status" else "id"
                    columns = sql.SQL(",").join(map(sql.Identifier, row))
                    existing = cur.execute(
                        sql.SQL("SELECT {} FROM {} WHERE {}=%s").format(
                            columns, sql.Identifier(table), sql.Identifier(key)
                        ),
                        (row[key],),
                    ).fetchone()
                    if existing is not None:
                        if times(existing) != row:
                            raise SeedConflict
                        continue
                    cur.execute(
                        sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
                            sql.Identifier(table),
                            columns,
                            sql.SQL(",").join(sql.Placeholder() * len(row)),
                        ),
                        [_value(table, k, v) for k, v in row.items()],
                    )
                    inserted[table] += 1
    return inserted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--yes", action="store_true", help="DATABASE_URL이 개발 DB임을 확인하고 추가"
    )
    args = parser.parse_args(argv)
    if not args.yes:
        print("개발 DB를 확인한 뒤 --yes를 지정하세요. DB에 연결하지 않았습니다.", file=sys.stderr)
        return 2
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("환경변수 DATABASE_URL이 필요합니다.", file=sys.stderr)
        return 2
    try:
        # 샘플 오류는 연결 전에 확인한다.
        load_seed()
        with psycopg.connect(url, connect_timeout=5, autocommit=True) as conn:
            counts = seed(conn)
    except (OSError, ValueError):
        print("시드 샘플 오류. DB 주소·원문은 출력하지 않습니다.", file=sys.stderr)
        return 2
    except (SeedConflict, psycopg.Error) as exc:
        print(f"시드를 적용하지 못했습니다: {type(exc).__name__}", file=sys.stderr)
        return 1
    print("dev-seed-ui 추가: " + ", ".join(f"{k} {v}" for k, v in counts.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
