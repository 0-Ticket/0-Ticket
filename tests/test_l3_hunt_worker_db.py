"""L3 헌팅 실행기 워커(#245, db 마커): 생성 워커의 차례·반복 방지, 검증 cancelled, 한 라운드 흐름.

가짜 실행(FakeRun)은 Agent Log를 쓰지 않는다. DB 쪽 "마지막 시도"는 시각을 정한 agent_logs 줄을
직접 넣거나(샘플 tests/fixtures/l3_hunt/hypothesize_logs.json), run_task + 가짜 모델 + DB 기록기로
실제 줄을 남겨 확인한다.
"""

import copy
import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any

import httpx
import psycopg
import pytest
from fake_model import FakeModel
from psycopg.types.json import Jsonb
from test_agent_executor import WAIT, executor_config, resolver
from test_l3_hunt_db import (
    EVT_1,
    FIXTURES,
    NOW,
    QUERY_EVENTS,
    FakeRun,
    add_hunt,
    conn,
    db,
    failed,
    ok,
    scenario,
    settings,
    verification,
    verifier,
)

from soc.agent import AgentResult, AgentTask
from soc.agent.agent_log import PostgresLogSink
from soc.agent.config import load_config as load_agent_config
from soc.agent.executor import Executor
from soc.agent.runner import run_task
from soc.contracts import to_epoch_ms, validate_contract
from soc.ids import new_id
from soc.l3.config import load_config
from soc.l3.hunt import store
from soc.l3.hunt.generate import SUBJECT_ID, HuntGenerator
from soc.l3.intel import collect as intel
from soc.tools import ToolRegistry

pytestmark = pytest.mark.db

__all__ = ["conn", "db"]  # fixture를 이 모듈에서도 쓴다

LOGS = json.loads((FIXTURES / "hypothesize_logs.json").read_text(encoding="utf-8"))["runs"]
INTERVAL = 86_400
HOUR = timedelta(hours=1)


class Clock:
    """가짜 시계. now를 바꿔 시간이 흐른 것처럼 한다."""

    def __init__(self, now: datetime = NOW) -> None:
        self.now = now

    def __call__(self) -> datetime:
        return self.now


def one_hypothesis() -> dict[str, Any]:
    return {"hypotheses": scenario("hypothesize_ok")["steps"][0]["final"]["hypotheses"][:1]}


def generator(
    db: str,
    run: Any,
    *,
    clock: Clock | None = None,
    intel_settings: intel.Settings | None = None,
    client_factory: Any = None,
    **hunt: Any,
) -> HuntGenerator:
    kwargs: dict[str, Any] = {}
    if client_factory is not None:
        kwargs["client_factory"] = client_factory
    return HuntGenerator(
        db,
        settings(**{"collect_before": intel_settings is not None, **hunt}),
        intel_settings,
        interval_seconds=INTERVAL,
        run=run,
        clock=clock or Clock(),
        **kwargs,
    )


def add_logs(conn: psycopg.Connection, name: str, started_at: datetime) -> str:
    """샘플의 run 하나를 agent_logs에 넣는다. 줄마다 1초씩 뒤에 시작한 것으로 한다."""
    run_id = new_id("run")
    subject_id = new_id("hrn")
    for i, template in enumerate(LOGS[name]):
        row = {
            **template,
            "id": new_id("agl"),
            "run_id": run_id,
            "subject_id": subject_id,
            "started_at": to_epoch_ms(started_at) + i * 1000,
        }
        validate_contract("agent_log", row)
        conn.execute(
            "INSERT INTO agent_logs (id, run_id, stage, subject_type, subject_id, seq, kind, name,"
            " input, output, outcome, tokens_in, tokens_out, started_at, duration_ms, details)"
            " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,"
            " to_timestamp(%s / 1000.0), %s, %s)",
            (
                row["id"],
                row["run_id"],
                row["stage"],
                row["subject_type"],
                row["subject_id"],
                row["seq"],
                row["kind"],
                row["name"],
                Jsonb(row["input"]),
                None if row["output"] is None else Jsonb(row["output"]),
                row["outcome"],
                row["tokens_in"],
                row["tokens_out"],
                row["started_at"],
                row["duration_ms"],
                Jsonb(row["details"]),
            ),
        )
    return run_id


def hunt_count(conn: psycopg.Connection) -> int:
    row = conn.execute("SELECT count(*) FROM hunts").fetchone()
    assert row is not None
    return row[0]


# 생성 워커: 차례


def test_generator_is_due_without_any_attempt_and_generates_once(
    db: str, conn: psycopg.Connection
) -> None:
    run = FakeRun(ok(one_hypothesis()))
    worker = generator(db, run)

    assert worker.stage == "l3"
    assert worker.name == "l3_hunt_hypothesize"
    assert worker.poll(10) == [SUBJECT_ID] == ["hypothesize"]
    worker.handle(SUBJECT_ID)
    worker.handle(SUBJECT_ID)  # 멱등: 차례가 지나 아무것도 하지 않는다

    assert [t.task for t in run.tasks] == ["l3_hypothesize"]
    assert hunt_count(conn) == 1
    assert worker.poll(10) == []


def test_generator_is_due_again_after_the_interval(db: str, conn: psycopg.Connection) -> None:
    clock = Clock()
    run = FakeRun(ok(one_hypothesis()), ok(one_hypothesis()))
    worker = generator(db, run, clock=clock)

    worker.handle(SUBJECT_ID)
    clock.now = NOW + timedelta(seconds=INTERVAL - 1)
    assert worker.poll(10) == []
    clock.now = NOW + timedelta(seconds=INTERVAL)
    assert worker.poll(10) == [SUBJECT_ID]
    worker.handle(SUBJECT_ID)

    assert len(run.tasks) == 2
    assert hunt_count(conn) == 2


def test_generator_ignores_other_subject_ids(db: str, conn: psycopg.Connection) -> None:
    worker = generator(db, FakeRun())

    worker.handle("hnt_not-mine")

    assert hunt_count(conn) == 0
    assert worker.poll(10) == [SUBJECT_ID]  # 시도로 세지 않았다


# 생성 워커: DB의 마지막 시도(재시작해도 지켜진다)


def test_recent_hypothesize_log_makes_it_not_due(db: str, conn: psycopg.Connection) -> None:
    add_logs(conn, "hypothesize_ok", NOW - HOUR)
    worker = generator(db, FakeRun())  # 불리면 AssertionError

    assert worker.poll(10) == []
    worker.handle(SUBJECT_ID)
    assert hunt_count(conn) == 0


def test_old_hypothesize_log_makes_it_due(db: str, conn: psycopg.Connection) -> None:
    add_logs(conn, "hypothesize_ok", NOW - timedelta(seconds=INTERVAL + 1))

    assert generator(db, FakeRun()).poll(10) == [SUBJECT_ID]


def test_failed_hypothesize_run_counts_as_an_attempt(db: str, conn: psycopg.Connection) -> None:
    add_logs(conn, "hypothesize_failed", NOW - HOUR)

    assert generator(db, FakeRun()).poll(10) == []


def test_cancelled_hypothesize_run_is_not_an_attempt(db: str, conn: psycopg.Connection) -> None:
    add_logs(conn, "hypothesize_ok", NOW - timedelta(seconds=INTERVAL + 1))
    add_logs(conn, "hypothesize_cancelled", NOW - HOUR)

    assert generator(db, FakeRun()).poll(10) == [SUBJECT_ID]


def test_verify_logs_are_not_hypothesize_attempts(db: str, conn: psycopg.Connection) -> None:
    add_logs(conn, "verify_ok", NOW - HOUR)

    assert generator(db, FakeRun()).poll(10) == [SUBJECT_ID]


def test_hypothesize_logs_written_by_run_task_are_read_after_restart(
    db: str, conn: psycopg.Connection
) -> None:
    """실제 기록기(PostgresLogSink)가 쓴 줄을 새 워커(재시작)가 마지막 시도로 읽는다."""
    model = FakeModel(scenario("hypothesize_ok"))
    config = copy.deepcopy(load_agent_config())
    config["tools"]["allowed"]["l3"] = [QUERY_EVENTS.name]

    def run(task: AgentTask) -> AgentResult:
        return run_task(
            task,
            model=model,
            model_name="fake-model",
            log_sink=PostgresLogSink(db),
            config=config,
            registry=ToolRegistry([QUERY_EVENTS]),
        )

    # Agent Log의 started_at은 실제 시계로 찍히므로 워커 시계도 실제 시각을 쓴다
    first = generator(db, run, clock=Clock(datetime.now(NOW.tzinfo)))
    first.handle(SUBJECT_ID)
    assert hunt_count(conn) >= 1

    restarted = generator(db, FakeRun(), clock=Clock(datetime.now(NOW.tzinfo)))
    assert restarted.poll(10) == []


# 생성 워커: Agent Log가 남지 않는 경우도 반복하지 않는다


def test_skipped_without_attack_is_not_repeated(db: str, conn: psycopg.Connection) -> None:
    conn.execute("DELETE FROM attack_techniques")
    worker = generator(db, FakeRun())

    worker.handle(SUBJECT_ID)

    assert worker.poll(10) == []
    assert hunt_count(conn) == 0


def test_run_failing_before_the_model_is_not_repeated(db: str, conn: psycopg.Connection) -> None:
    run = FakeRun(failed("provider_error"))  # 가짜 실행은 Agent Log를 쓰지 않는다
    worker = generator(db, run)

    worker.handle(SUBJECT_ID)
    worker.handle(SUBJECT_ID)

    assert len(run.tasks) == 1
    assert worker.poll(10) == []
    assert hunt_count(conn) == 0


def test_exception_in_handle_is_not_repeated(db: str, conn: psycopg.Connection) -> None:
    def broken(task: AgentTask) -> AgentResult:
        raise RuntimeError("실행 중 예외(테스트)")

    worker = generator(db, broken)

    with pytest.raises(RuntimeError):
        worker.handle(SUBJECT_ID)

    assert worker.poll(10) == []


def test_restart_retries_an_attempt_that_left_no_log(db: str, conn: psycopg.Connection) -> None:
    conn.execute("DELETE FROM attack_techniques")
    generator(db, FakeRun()).handle(SUBJECT_ID)

    assert generator(db, FakeRun()).poll(10) == [SUBJECT_ID]


# 생성 워커: 수집


def test_generator_collects_first_and_continues_when_collect_fails(
    db: str, conn: psycopg.Connection
) -> None:
    requested: list[str] = []

    def failing_web(_: Any) -> httpx.Client:
        def handler(request: httpx.Request) -> httpx.Response:
            requested.append(str(request.url))
            return httpx.Response(500)

        return httpx.Client(transport=httpx.MockTransport(handler))

    run = FakeRun(ok(one_hypothesis()))
    intel_settings = intel.read_settings(load_config()["l3"])
    worker = generator(db, run, intel_settings=intel_settings, client_factory=failing_web)

    worker.handle(SUBJECT_ID)

    assert requested  # 출처를 가져오려 했다(ATT&CK 20.0은 이미 있어 건너뜀)
    assert [t.task for t in run.tasks] == ["l3_hypothesize"]
    assert hunt_count(conn) == 1


def test_generator_logs_counts_only(
    db: str, conn: psycopg.Connection, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="soc.l3.hunt.generate")
    worker = generator(db, FakeRun(ok(one_hypothesis())))

    worker.handle(SUBJECT_ID)

    assert "가설 생성: 저장 1" in caplog.text
    assert "웹셸" not in caplog.text  # 가설 문장
    assert "INJECTED" not in caplog.text  # 뉴스 제목


def test_generator_logs_failure_kind(
    db: str, conn: psycopg.Connection, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.INFO, logger="soc.l3.hunt.generate")

    generator(db, FakeRun(failed("rate_limited"))).handle(SUBJECT_ID)

    assert "실패 rate_limited" in caplog.text
    assert hunt_count(conn) == 0


# 검증 워커: cancelled


def test_cancelled_verify_run_leaves_hunt_unchanged(db: str, conn: psycopg.Connection) -> None:
    hunt_id = add_hunt(conn, attempts=1)
    before = store.read_hunt(conn, hunt_id)
    run = FakeRun(failed("cancelled"), failed("cancelled"), failed("cancelled"))
    worker = verifier(db, run)  # max_attempts 2

    for _ in range(3):
        worker.handle(hunt_id)

    assert store.read_hunt(conn, hunt_id) == before
    assert worker.poll(10) == [hunt_id]
    assert [t.attempt for t in run.tasks] == [2, 2, 2]


def test_other_failures_still_reach_failed_after_a_cancel(
    db: str, conn: psycopg.Connection
) -> None:
    hunt_id = add_hunt(conn)
    run = FakeRun(failed("cancelled"), failed("provider_error"), failed("cancelled"))
    run.results.append(failed("log_error"))  # 앞 실패가 cancelled여도 log_error는 실패로 센다
    worker = verifier(db, run)

    for _ in range(4):
        worker.handle(hunt_id)

    hunt = store.read_hunt(conn, hunt_id)
    assert hunt is not None
    assert (hunt["status"], hunt["attempts"]) == ("failed", 2)
    failures = [f["failure"] for f in hunt["details"]["verify_failures"]]
    assert failures == ["provider_error", "log_error"]


# 한 라운드: 생성 → 검증(등록 순서)


def test_one_round_generates_then_verifies_the_new_hunt(db: str, conn: psycopg.Connection) -> None:
    run = FakeRun(ok(one_hypothesis()), ok(verification("rejected", 0.8, [EVT_1])))
    workers = {"gen": generator(db, run), "verify": verifier(db, run)}
    config = executor_config(
        {"l3": {"interval_seconds": 3600, "workers": ["soc.test:gen", "soc.test:verify"]}}
    )
    executor = Executor(config, resolve=resolver(workers))

    executor.start()
    deadline = time.monotonic() + WAIT
    while len(run.tasks) < 2 and time.monotonic() < deadline:
        time.sleep(0.02)
    assert executor.stop() == []

    assert [t.task for t in run.tasks] == ["l3_hypothesize", "l3_verify"]
    hunt_id = run.tasks[1].subject_id
    hunt = store.read_hunt(conn, hunt_id)
    assert hunt is not None
    assert hunt["status"] == "rejected"
