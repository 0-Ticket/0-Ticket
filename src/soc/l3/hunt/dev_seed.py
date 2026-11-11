"""개발 DB 전용 시드(#224): 검증 run을 실제 모델로 잴 때 쓸 pending Hunt 2개와 근거 레코드.

샘플은 tests/fixtures/l3_hunt/dev_seed.json(손으로 만든 값)이다. 위협 있음(근거 Alert·Event가
있음)과 위협 없음(가설에 맞는 레코드가 없음) 두 시나리오다. 레코드 시각은 넣는 시점의 지금에서
ago_ms를 빼서 검증 run의 조회 기간(lookback_days) 안에 들어가게 한다.

표시와 지우기
- Hunt: details.dev_seed = true(시나리오 이름은 details.scenario)
- RawRecord: siem_profile = "dev-seed". Alert·Event는 이 RawRecord를 가리키는 것(raw_id)으로
  찾는다. Alert·Event의 details에는 표시를 넣지 않는다. 에이전트 도구가 details를 모델에게 보여
  주기 때문이다
- 시드 Hunt의 L3 Ticket도 함께 지운다. Agent Log는 실측 원본이라 지우지 않는다
- 시드 Ticket이 Incident에 붙어 있으면 아무것도 지우지 않는다(SeedInUse)
"""

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from soc.contracts import to_datetime, to_epoch_ms, validate_contract
from soc.ids import new_id
from soc.l3.hunt import store

SEED_PATH = Path(__file__).resolve().parents[4] / "tests" / "fixtures" / "l3_hunt" / "dev_seed.json"
SEED_PROFILE = "dev-seed"
SEED_MARK = Jsonb({"dev_seed": True})

_RAW_COLUMNS = ("id", "kind", "siem_profile", "siem_ref", "fetched_at", "original_text")
_ALERT_COLUMNS = (
    "id",
    "raw_id",
    "time",
    "severity",
    "title",
    "rule_id",
    "entities",
    "assets",
    "triage",
    "ocsf",
    "details",
)
_EVENT_COLUMNS = (
    "id",
    "raw_id",
    "time",
    "ocsf_class",
    "summary",
    "entities",
    "assets",
    "ocsf",
    "details",
)
_TIMES = ("fetched_at", "time")
_JSONB = ("entities", "assets", "triage", "ocsf", "details")


class SeedInUse(Exception):
    """시드 Ticket이 Incident에 붙어 있어 지우지 않았다."""

    def __init__(self, incidents: int) -> None:
        super().__init__(f"시드 Ticket이 Incident {incidents}건에 붙어 있다")
        self.incidents = incidents


@dataclass(frozen=True)
class SeedRows:
    raw_records: list[dict[str, Any]]
    alerts: list[dict[str, Any]]
    events: list[dict[str, Any]]
    hunts: list[dict[str, Any]]


@dataclass(frozen=True)
class SeedResult:
    removed: dict[str, int]
    inserted: dict[str, int]
    hunt_ids: dict[str, str]  # 시나리오 이름 → Hunt ID


def load_seed(path: Path = SEED_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def build_rows(seed_data: Mapping[str, Any], now_ms: int) -> SeedRows:
    """샘플을 계약 모양의 행으로 바꾼다. ID는 매번 새로 만든다. 틀린 샘플은 ValueError."""
    hunt_run_id = new_id("hrn")
    rows = SeedRows([], [], [], [])
    for scenario in seed_data["scenarios"]:
        name = scenario["name"]
        for kind, records in (("alert", scenario["alerts"]), ("event", scenario["events"])):
            for n, record in enumerate(records, start=1):
                time_ms = now_ms - _ago(record)
                raw = {
                    "id": new_id("raw"),
                    "kind": kind,
                    "siem_profile": SEED_PROFILE,
                    "siem_ref": f"{name}/{kind}/{n}",
                    "fetched_at": time_ms,
                    "original_text": json.dumps(record["original"], ensure_ascii=True),
                }
                if kind == "alert":
                    row = {
                        "id": new_id("alt"),
                        "raw_id": raw["id"],
                        "time": time_ms,
                        "severity": record["severity"],
                        "title": record["title"],
                        "rule_id": record["rule_id"],
                        "entities": record["entities"],
                        "assets": [],
                        "triage": None,
                        "ocsf": record["ocsf"],
                        "details": {},
                    }
                    rows.alerts.append(row)
                else:
                    row = {
                        "id": new_id("evt"),
                        "raw_id": raw["id"],
                        "time": time_ms,
                        "ocsf_class": record["ocsf"]["class_uid"],
                        "summary": record["summary"],
                        "entities": record["entities"],
                        "assets": [],
                        "ocsf": record["ocsf"],
                        "details": {},
                    }
                    rows.events.append(row)
                validate_contract("raw_record", raw)
                validate_contract(kind, row)
                rows.raw_records.append(raw)
        hunt = {
            "id": new_id("hnt"),
            "hunt_run_id": hunt_run_id,
            "status": "pending",
            "hypothesis": scenario["hunt"]["hypothesis"],
            "attack_techniques": scenario["hunt"]["attack_techniques"],
            "confidence": None,
            "reason": None,
            "evidence_ids": [],
            "entities": [],
            "attempts": 0,
            "verified_at": None,
            "created_at": now_ms,
            "updated_at": now_ms,
            "details": {"dev_seed": True, "scenario": name},
        }
        validate_contract("hunt", hunt)
        rows.hunts.append(hunt)
    return rows


def _ago(record: Mapping[str, Any]) -> int:
    ago = record["ago_ms"]
    if isinstance(ago, bool) or not isinstance(ago, int) or ago <= 0:
        raise ValueError("ago_ms는 1 이상의 정수다")
    return ago


def remove_seed(conn: psycopg.Connection) -> dict[str, int]:
    """시드 행만 한 트랜잭션으로 지운다. 지운 건수. 시드 Ticket이 Incident에 있으면 SeedInUse."""
    with conn.transaction():
        hunt_ids = [
            row[0]
            for row in conn.execute(
                "SELECT id FROM hunts WHERE details @> %s FOR UPDATE", (SEED_MARK,)
            ).fetchall()
        ]
        ticket_ids = [
            row[0]
            for row in conn.execute(
                "SELECT id FROM tickets WHERE hunt_id = ANY(%s) FOR UPDATE", (hunt_ids,)
            ).fetchall()
        ]
        (in_use,) = conn.execute(
            "SELECT count(*) FROM incidents WHERE ticket_ids && %s::text[]", (ticket_ids,)
        ).fetchone()  # type: ignore[misc]
        if in_use:
            raise SeedInUse(in_use)
        removed = {
            "tickets": _delete(conn, "DELETE FROM tickets WHERE id = ANY(%s)", ticket_ids),
            "hunts": _delete(conn, "DELETE FROM hunts WHERE id = ANY(%s)", hunt_ids),
        }
        seeded_raw = "SELECT id FROM raw_records WHERE siem_profile = %s"
        for table in ("alerts", "events"):
            removed[table] = _delete(
                conn,
                f"DELETE FROM {table} WHERE raw_id IN ({seeded_raw})",  # 테이블 이름은 상수다
                SEED_PROFILE,
            )
        removed["raw_records"] = _delete(
            conn, "DELETE FROM raw_records WHERE siem_profile = %s", SEED_PROFILE
        )
    return removed


def _delete(conn: psycopg.Connection, query: str, param: Any) -> int:
    return conn.execute(query, (param,)).rowcount


def seed(
    conn: psycopg.Connection, *, now: datetime, seed_data: Mapping[str, Any] | None = None
) -> SeedResult:
    """이전 시드를 지우고 새로 넣는다(한 트랜잭션). 지우지 못하면 SeedInUse이고 넣지 않는다."""
    rows = build_rows(load_seed() if seed_data is None else seed_data, to_epoch_ms(now))
    with conn.transaction():
        removed = remove_seed(conn)
        _insert(conn, "raw_records", _RAW_COLUMNS, rows.raw_records)
        _insert(conn, "alerts", _ALERT_COLUMNS, rows.alerts)
        _insert(conn, "events", _EVENT_COLUMNS, rows.events)
        store.insert_hunts(conn, rows.hunts)
    return SeedResult(
        removed=removed,
        inserted={
            "hunts": len(rows.hunts),
            "alerts": len(rows.alerts),
            "events": len(rows.events),
            "raw_records": len(rows.raw_records),
        },
        hunt_ids={h["details"]["scenario"]: h["id"] for h in rows.hunts},
    )


def _insert(
    conn: psycopg.Connection, table: str, columns: Sequence[str], rows: Sequence[dict[str, Any]]
) -> None:
    query = (
        f"INSERT INTO {table} ({', '.join(columns)})"  # 테이블·컬럼 이름은 상수다
        f" VALUES ({', '.join(['%s'] * len(columns))})"
    )
    with conn.cursor() as cur:
        cur.executemany(query, [[_db_value(c, row[c]) for c in columns] for row in rows])


def _db_value(column: str, value: Any) -> Any:
    if value is None:
        return None
    if column in _TIMES:
        return to_datetime(value)
    if column in _JSONB:
        return Jsonb(value)
    return value


def _utcnow() -> datetime:
    return datetime.now(UTC)


def _format(counts: Mapping[str, int]) -> str:
    return ", ".join(f"{name} {count}" for name, count in counts.items())


def run_dev_seed(
    database_url: str | None,
    *,
    remove: bool = False,
    clock: Callable[[], datetime] = _utcnow,
    out: Callable[[str], None] = print,
    err: Callable[[str], None] = print,
) -> int:
    """uv run python -m soc.l3 dev-seed [--remove]의 본체.

    종료 코드: 0 정상, 1 시드가 Incident에 붙어 지우지 않음 또는 DB 오류, 2 DATABASE_URL·샘플 오류.
    출력은 건수와 시드 Hunt ID뿐이다. 가설 본문과 DB 주소는 출력하지 않는다.
    """
    if not database_url:
        err("환경변수 DATABASE_URL이 없다. .env.example을 참고해 설정한다.")
        return 2
    try:
        seed_data = None if remove else load_seed()
    except (OSError, ValueError) as exc:
        err(f"시드 샘플을 읽지 못했다({type(exc).__name__})")
        return 2
    out("개발 DB 전용: DATABASE_URL이 가리키는 DB의 시드 행만 다룬다")
    try:
        with psycopg.connect(database_url, autocommit=True) as conn:
            if remove:
                out(f"지움: {_format(remove_seed(conn))}")
                return 0
            made = seed(conn, now=clock(), seed_data=seed_data)
    except SeedInUse as exc:
        err(
            f"지우지 않았다: 시드 Ticket이 Incident {exc.incidents}건에 붙어 있다."
            " 개발 DB를 다시 만들거나 그 Incident를 먼저 정리한다"
        )
        return 1
    except ValueError as exc:
        err(f"시드 샘플이 계약에 맞지 않는다({type(exc).__name__})")
        return 2
    except psycopg.Error as exc:
        # 원래 예외 메시지에는 접속 대상 주소가 들어 있을 수 있어 종류만 남긴다.
        err(f"DB 오류({type(exc).__name__}). DATABASE_URL과 마이그레이션을 확인한다")
        return 1
    out(f"지움: {_format(made.removed)}")
    out(f"넣음: {_format(made.inserted)}")
    out(f"위협 있음 Hunt: {made.hunt_ids['threat']}")
    out(f"위협 없음 Hunt: {made.hunt_ids['no_threat']}")
    return 0
