"""개발 DB 전용 L1 실측 명령(#215): uv run python -m soc.agent.dev_l1 seed|run|remove

L1 워커 없이 L1 판정 작업(AgentTask)을 run_agent에 직접 넣어, 실제 모델로 도구 호출 → Verdict →
Agent Log를 끝까지 돌리고 턴·토큰을 잰다. 4층 작업 프롬프트와 입력(data) 모양은 측정용이고
L1 코드가 아니다. L1 담당이 정할 모양과 다를 수 있다. Alert에 판정 결과(triage)는 쓰지 않는다.

- seed: 이전 시드를 지우고 tests/fixtures/l1_e2e/dev_seed.json의 Alert·Event를 넣는다(한 트랜잭션).
  레코드 시각은 넣는 시점의 지금에서 ago_ms를 뺀다
- run: 시드 Alert마다 run_agent를 한 번 부른다. 출력은 시나리오 이름과 숫자, decision·failure뿐이다
  (이유 본문 없음)
- remove: 시드 행만 지운다. Agent Log는 실측 원본이라 지우지 않는다

시드 표시는 RawRecord siem_profile = "dev-seed-l1"이다. Alert·Event는 이 RawRecord를 가리키는 것
(raw_id)으로 찾는다. L3 시드(siem_profile "dev-seed", #224)와 이름이 달라 서로 지우지 않는다.
Alert·Event의 details에는 표시를 넣지 않는다. 에이전트 도구가 details를 모델에게 보여 주기 때문이다.
"""

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from soc.agent.runner import run_agent
from soc.agent.types import AgentResult, AgentTask, TaskPrompt
from soc.contracts import to_datetime, to_epoch_ms, validate_contract
from soc.ids import new_id

SEED_PATH = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "l1_e2e" / "dev_seed.json"
SEED_PROFILE = "dev-seed-l1"
TASK_NAME = "l1_e2e_probe"

_RAW_COLUMNS = ("id", "kind", "siem_profile", "siem_ref", "fetched_at", "original")
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
_JSONB = ("original", "entities", "assets", "triage", "ocsf", "details")

Run = Callable[[AgentTask], AgentResult]


@dataclass(frozen=True)
class SeedRows:
    raw_records: list[dict[str, Any]]
    alerts: list[dict[str, Any]]
    events: list[dict[str, Any]]


@dataclass(frozen=True)
class SeededAlert:
    scenario: str
    alert: dict[str, Any]  # 모델에게 보여 줄 칸만: id, time, severity, title, rule_id, entities


def load_seed(path: Path = SEED_PATH) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def task_prompt(seed_data: Mapping[str, Any]) -> TaskPrompt:
    """측정용 4층 작업 프롬프트. 버전은 본문의 sha256이다."""
    text = seed_data["task_prompt"]
    return TaskPrompt(text=text, version=hashlib.sha256(text.encode("utf-8")).hexdigest())


def build_rows(seed_data: Mapping[str, Any], now_ms: int) -> SeedRows:
    """샘플을 계약 모양의 행으로 바꾼다. ID는 매번 새로 만든다. 틀린 샘플은 ValueError."""
    rows = SeedRows([], [], [])
    for scenario in seed_data["scenarios"]:
        name = scenario["name"]
        records = [("alert", 1, scenario["alert"])]
        records += [("event", n, e) for n, e in enumerate(scenario["events"], start=1)]
        for kind, n, record in records:
            time_ms = now_ms - _ago(record)
            raw = {
                "id": new_id("raw"),
                "kind": kind,
                "siem_profile": SEED_PROFILE,
                "siem_ref": f"{name}/{kind}/{n}",
                "fetched_at": time_ms,
                "original": record["original"],
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
    return rows


def _ago(record: Mapping[str, Any]) -> int:
    ago = record["ago_ms"]
    if isinstance(ago, bool) or not isinstance(ago, int) or ago <= 0:
        raise ValueError("ago_ms는 1 이상의 정수다")
    return ago


def remove_seed(conn: psycopg.Connection) -> dict[str, int]:
    """시드 행만 한 트랜잭션으로 지운다. 지운 건수. Agent Log는 지우지 않는다."""
    seeded_raw = "SELECT id FROM raw_records WHERE siem_profile = %s"
    removed = {}
    with conn.transaction():
        for table in ("alerts", "events"):
            removed[table] = conn.execute(
                f"DELETE FROM {table} WHERE raw_id IN ({seeded_raw})",  # 테이블 이름은 상수다
                (SEED_PROFILE,),
            ).rowcount
        removed["raw_records"] = conn.execute(
            "DELETE FROM raw_records WHERE siem_profile = %s", (SEED_PROFILE,)
        ).rowcount
    return removed


def seed(
    conn: psycopg.Connection, *, now: datetime, seed_data: Mapping[str, Any] | None = None
) -> tuple[dict[str, int], dict[str, int]]:
    """이전 시드를 지우고 새로 넣는다(한 트랜잭션). (지운 건수, 넣은 건수)."""
    rows = build_rows(load_seed() if seed_data is None else seed_data, to_epoch_ms(now))
    with conn.transaction():
        removed = remove_seed(conn)
        _insert(conn, "raw_records", _RAW_COLUMNS, rows.raw_records)
        _insert(conn, "alerts", _ALERT_COLUMNS, rows.alerts)
        _insert(conn, "events", _EVENT_COLUMNS, rows.events)
    inserted = {
        "alerts": len(rows.alerts),
        "events": len(rows.events),
        "raw_records": len(rows.raw_records),
    }
    return removed, inserted


def seeded_alerts(conn: psycopg.Connection) -> list[SeededAlert]:
    """시드 Alert(시나리오 이름 순)."""
    rows = conn.execute(
        "SELECT r.siem_ref, a.id, floor(extract(epoch FROM a.time) * 1000)::bigint,"
        " a.severity, a.title, a.rule_id, a.entities"
        " FROM alerts a JOIN raw_records r ON r.id = a.raw_id"
        " WHERE r.siem_profile = %s AND r.kind = 'alert' ORDER BY r.siem_ref",
        (SEED_PROFILE,),
    ).fetchall()
    return [
        SeededAlert(
            scenario=ref.split("/", 1)[0],
            alert={
                "id": alert_id,
                "time": time_ms,
                "severity": severity,
                "title": title,
                "rule_id": rule_id,
                "entities": entities,
            },
        )
        for ref, alert_id, time_ms, severity, title, rule_id, entities in rows
    ]


def build_task(alert: Mapping[str, Any], prompt: TaskPrompt) -> AgentTask:
    """Alert 하나의 L1 1차 판정 작업. 근거 장부는 그 Alert ID로 시작한다."""
    return AgentTask(
        stage="l1",
        task=TASK_NAME,
        prompt=prompt,
        data={"alert": dict(alert)},
        output_contract="verdict",
        cited_ids=lambda output: output["evidence_ids"],
        subject_type="alert",
        subject_id=alert["id"],
        allowed_evidence_ids=(alert["id"],),
    )


def format_result(scenario: str, expected: str, result: AgentResult) -> str:
    """한 줄 결과. 이유(reason) 본문과 모델 출력 문장은 넣지 않는다."""
    output = result.output if isinstance(result.output, dict) else {}
    usage = result.usage
    fields = [
        scenario,
        f"expected={expected}",
        f"ok={result.ok}",
        f"failure={result.failure or '-'}",
        f"decision={output.get('decision', '-')}",
        f"confidence={output.get('confidence', '-')}",
        f"evidence={len(result.cited_evidence_ids)}",
        *(
            f"{key}={usage.get(key, 0)}"
            for key in ("turns", "tool_calls", "tool_errors", "tokens_in", "tokens_out")
        ),
        f"ms={usage.get('duration_ms', 0)}",
        f"run_id={result.run_id}",
    ]
    return " ".join(fields)


def run_probe(
    conn: psycopg.Connection,
    seed_data: Mapping[str, Any],
    *,
    run: Run = run_agent,
    out: Callable[[str], None] = print,
) -> int:
    """시드 Alert마다 run을 한 번 부르고 한 줄씩 출력한다. 돌린 건수."""
    expected = {s["name"]: s["expected"] for s in seed_data["scenarios"]}
    prompt = task_prompt(seed_data)
    alerts = seeded_alerts(conn)
    for seeded in alerts:
        result = run(build_task(seeded.alert, prompt))
        out(format_result(seeded.scenario, expected.get(seeded.scenario, "-"), result))
    return len(alerts)


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


def _format(counts: Mapping[str, int]) -> str:
    return ", ".join(f"{name} {count}" for name, count in counts.items())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m soc.agent.dev_l1",
        description=(
            "개발 DB 전용 L1 실측(#215). 운영 DB에 쓰지 않는다."
            " tests/fixtures/l1_e2e/dev_seed.json의"
            " Alert·Event를 넣고, L1 워커 없이 run_agent로 Alert마다 판정을 한 번씩 돌린다"
        ),
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("seed", help="이전 시드를 지우고 다시 넣는다")
    commands.add_parser("run", help="시드 Alert마다 run_agent를 한 번 부른다(실제 모델 호출)")
    commands.add_parser("remove", help="시드 행만 지운다(Agent Log는 남김)")
    return parser


def main(
    argv: list[str] | None = None,
    *,
    run: Run = run_agent,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    out: Callable[[str], None] = print,
    err: Callable[[str], None] = lambda line: print(line, file=sys.stderr),
) -> int:
    """종료 코드: 0 정상, 1 DB 오류, 2 DATABASE_URL·샘플 오류 또는 시드 없음."""
    args = build_parser().parse_args(argv)
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        err("환경변수 DATABASE_URL이 없다. .env.example을 참고해 설정한다.")
        return 2
    try:
        seed_data = load_seed()
        task_prompt(seed_data)
    except (OSError, ValueError, KeyError) as exc:
        err(f"시드 샘플을 읽지 못했다({type(exc).__name__})")
        return 2
    out("개발 DB 전용: DATABASE_URL이 가리키는 DB의 L1 시드 행만 다룬다")
    try:
        with psycopg.connect(database_url, autocommit=True) as conn:
            if args.command == "remove":
                out(f"지움: {_format(remove_seed(conn))}")
            elif args.command == "seed":
                removed, inserted = seed(conn, now=clock(), seed_data=seed_data)
                out(f"지움: {_format(removed)}")
                out(f"넣음: {_format(inserted)}")
            elif run_probe(conn, seed_data, run=run, out=out) == 0:
                err("시드 Alert가 없다. 먼저 seed를 실행한다")
                return 2
    except ValueError as exc:
        err(f"시드 샘플이 계약에 맞지 않는다({type(exc).__name__})")
        return 2
    except psycopg.Error as exc:
        # 원래 예외 메시지에는 접속 대상 주소가 들어 있을 수 있어 종류만 남긴다.
        err(f"DB 오류({type(exc).__name__}). DATABASE_URL과 마이그레이션을 확인한다")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
