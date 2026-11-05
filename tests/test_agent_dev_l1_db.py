"""L1 실측 시드 넣기·지우기와 run을 실제 PostgreSQL로 확인한다(#215, db 마커).

모델은 부르지 않는다.
"""

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
import pytest

from soc.agent import AgentResult, AgentTask
from soc.agent.agent_log import PostgresLogSink
from soc.agent.dev_l1 import (
    SEED_PROFILE,
    TASK_NAME,
    load_seed,
    main,
    remove_seed,
    run_probe,
    seed,
    seeded_alerts,
)
from soc.db.migrate import migrate
from soc.ids import new_id
from soc.l3.hunt import dev_seed as l3_seed

pytestmark = pytest.mark.db

FIXTURES = Path(__file__).parent / "fixtures"
AGENT_LOG = json.loads((FIXTURES / "contracts" / "valid" / "agent_log.json").read_text("utf-8"))
NOW = datetime(2026, 11, 5, 3, 0, tzinfo=UTC)
TABLES = ("raw_records", "alerts", "events", "hunts")
SEED_COUNTS = {"alerts": 6, "events": 17, "raw_records": 23}


@pytest.fixture
def db(temp_database: str) -> str:
    migrate(temp_database)
    return temp_database


@pytest.fixture
def conn(db: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(db, autocommit=True) as connection:
        yield connection


def counts(conn: psycopg.Connection) -> dict[str, int]:
    return {t: conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0] for t in TABLES}  # type: ignore[index]


def test_seed_inserts_six_alerts_with_events(conn: psycopg.Connection) -> None:
    removed, inserted = seed(conn, now=NOW)

    assert removed == {"alerts": 0, "events": 0, "raw_records": 0}
    assert inserted == SEED_COUNTS
    assert counts(conn) == {**SEED_COUNTS, "hunts": 0}
    profiles = conn.execute("SELECT DISTINCT siem_profile FROM raw_records").fetchall()
    assert profiles == [(SEED_PROFILE,)]
    assert conn.execute("SELECT count(*) FROM alerts WHERE triage IS NOT NULL").fetchone() == (0,)
    (oldest, newest) = conn.execute("SELECT min(time), max(time) FROM events").fetchone()  # type: ignore[misc]
    assert (NOW - oldest).days < 7 and newest < NOW


def test_seed_again_replaces_previous_seed(conn: psycopg.Connection) -> None:
    seed(conn, now=NOW)
    first = {a.alert["id"] for a in seeded_alerts(conn)}

    removed, _ = seed(conn, now=NOW)

    assert removed == SEED_COUNTS
    assert counts(conn) == {**SEED_COUNTS, "hunts": 0}
    assert first.isdisjoint({a.alert["id"] for a in seeded_alerts(conn)})


def test_remove_keeps_l3_seed_and_agent_logs(db: str, conn: psycopg.Connection) -> None:
    l3_seed.seed(conn, now=NOW)
    l3_only = counts(conn)
    seed(conn, now=NOW)
    alert_id = seeded_alerts(conn)[0].alert["id"]
    PostgresLogSink(db).write(
        [{**AGENT_LOG[0]["data"], "stage": "l1", "subject_type": "alert", "subject_id": alert_id}]
    )

    assert remove_seed(conn) == SEED_COUNTS

    assert counts(conn) == l3_only
    assert conn.execute("SELECT count(*) FROM agent_logs").fetchone() == (1,)
    # L3 시드를 다시 넣어도 L1 시드는 지워지지 않는다(siem_profile이 다르다)
    seed(conn, now=NOW)
    l3_seed.seed(conn, now=NOW)
    assert len(seeded_alerts(conn)) == 6


def test_seeded_alerts_show_only_model_fields(conn: psycopg.Connection) -> None:
    seed(conn, now=NOW)
    alerts = seeded_alerts(conn)
    assert [a.scenario for a in alerts] == sorted(s["name"] for s in load_seed()["scenarios"])
    for seeded in alerts:
        assert set(seeded.alert) == {"id", "time", "severity", "title", "rule_id", "entities"}
        assert isinstance(seeded.alert["time"], int)


def test_run_calls_run_once_per_seeded_alert(conn: psycopg.Connection) -> None:
    seed(conn, now=NOW)
    tasks: list[AgentTask] = []
    lines: list[str] = []

    def fake_run(task: AgentTask) -> AgentResult:
        tasks.append(task)
        output = {
            "decision": "undetermined",
            "confidence": 0.5,
            "reason": "이유 본문",
            "evidence_ids": [],
            "decided_at": 0,
        }
        return AgentResult(ok=True, output=output, failure=None, detail=None, run_id=new_id("run"))

    assert run_probe(conn, load_seed(), run=fake_run, out=lines.append) == 6

    alert_ids = [a.alert["id"] for a in seeded_alerts(conn)]
    assert [t.subject_id for t in tasks] == alert_ids
    assert all(t.task == TASK_NAME and t.allowed_evidence_ids == (t.subject_id,) for t in tasks)
    assert len(lines) == 6 and not any("이유 본문" in line for line in lines)
    # 판정 결과는 Alert에 쓰지 않는다(L1 워커의 일)
    assert conn.execute("SELECT count(*) FROM alerts WHERE triage IS NOT NULL").fetchone() == (0,)


def test_main_commands(db: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", db)
    out: list[str] = []
    err: list[str] = []
    calls: list[Any] = []

    def fake_run(task: AgentTask) -> AgentResult:
        calls.append(task)
        return AgentResult(
            ok=False, output=None, failure="provider_error", detail=None, run_id=new_id("run")
        )

    def cli(*argv: str) -> int:
        return main(list(argv), run=fake_run, clock=lambda: NOW, out=out.append, err=err.append)

    assert cli("run") == 2  # 시드가 없다
    assert "seed" in err[-1]
    assert cli("seed") == 0
    assert any(line.startswith("넣음: alerts 6") for line in out)
    assert cli("run") == 0
    assert len(calls) == 6
    assert cli("remove") == 0
    assert out[-1] == "지움: alerts 6, events 17, raw_records 23"
