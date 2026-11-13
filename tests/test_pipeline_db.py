"""활성화 파이프를 실제 PostgreSQL로 본다(#316, db 마커).

샘플은 tests/fixtures/lab_cycle/의 손 샘플을 그대로 쓴다. 모델·임베더·ELK는 가짜다.
정규화·Ticket 생성은 실제 파이프 워커를 쓰고, L1·L2만 가짜 실행 함수를 끼운다.
"""

import secrets
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from conftest import HiddenUrl
from psycopg import sql
from psycopg.conninfo import make_conninfo
from test_lab_cycle_db import (
    ANALYZE,
    NORMALIZE,
    NOW,
    MemoryVectorStore,
    analyze_run,
    branch_worker,
    counts,
    ingest_once,
    l1_run,
    q,
)
from test_pipeline_check import ENV, OK_PROBES

from soc.agent import AgentResult
from soc.agent.executor import resolve_factory
from soc.db.migrate import MigrationError, find_migrations, migrate, unapplied_migrations
from soc.ids import new_id
from soc.l1.judge import L1Worker
from soc.l2.analyze.worker import L2AnalyzeWorker
from soc.normalize.run import run as normalize_run
from soc.pipeline import __main__ as pipeline_main
from soc.pipeline.workers import NormalizeWorker, TicketingWorker

pytestmark = pytest.mark.db

WAIT = 30.0
FAST = """
[executor.l1]
interval_seconds = 0.1
[executor.l2]
interval_seconds = 0.1
[pipeline]
normalize_interval_seconds = 0.1
ticketing_interval_seconds = 0.1
"""


@pytest.fixture
def db(temp_database: HiddenUrl) -> HiddenUrl:
    migrate(temp_database)
    return temp_database


@pytest.fixture
def conn(db: HiddenUrl) -> Iterator[psycopg.Connection]:
    with psycopg.connect(db, autocommit=True) as connection:
        yield connection


@pytest.fixture
def reader_url(db: HiddenUrl, monkeypatch: pytest.MonkeyPatch) -> Iterator[HiddenUrl]:
    """L1 도구(get_alert)가 접속할 soc_agent_reader 멤버 임시 LOGIN 역할. 끝나면 지운다."""
    name = f"soc_test_reader_{secrets.token_hex(4)}"
    password = secrets.token_urlsafe(16)
    with psycopg.connect(db, autocommit=True) as admin:
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE {}").format(
                sql.Identifier(name), sql.Literal(password), sql.Identifier("soc_agent_reader")
            )
        )
    url = HiddenUrl(make_conninfo(db, user=name, password=password))
    monkeypatch.setenv("AGENT_DATABASE_URL", url)
    try:
        yield url
    finally:
        with psycopg.connect(db, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(name)))


# 마이그레이션 상태 읽기


def test_unapplied_migrations_reads_without_applying(temp_database: HiddenUrl) -> None:
    names = [m.name for m in find_migrations()]
    assert unapplied_migrations(temp_database) == names
    # 읽기만 했으므로 아무것도 적용되지 않았다
    assert unapplied_migrations(temp_database) == names
    migrate(temp_database)
    assert unapplied_migrations(temp_database) == []


def test_unapplied_migrations_rejects_a_changed_record(
    db: HiddenUrl, conn: psycopg.Connection
) -> None:
    conn.execute("UPDATE schema_migrations SET checksum = 'x' WHERE version = 1")
    with pytest.raises(MigrationError):
        unapplied_migrations(db)


def test_unapplied_migrations_lists_only_the_missing_ones(
    db: HiddenUrl, conn: psycopg.Connection
) -> None:
    last = find_migrations()[-1]
    conn.execute("DELETE FROM schema_migrations WHERE version = %s", (last.version,))
    assert unapplied_migrations(db) == [last.name]


# 워커의 poll 조건은 기존 run()이 집는 대상과 같다


def test_normalize_poll_agrees_with_what_run_claims(
    db: HiddenUrl, conn: psycopg.Connection
) -> None:
    worker = NormalizeWorker(db, NORMALIZE)
    assert worker.poll(1) == []
    ingest_once(conn)
    assert worker.poll(1) != []  # 상태 행이 아직 없는 원본

    # 임대가 걸려 있는 pending은 집지 않는다
    worker.handle(worker.poll(1)[0])
    assert worker.poll(1) == []
    conn.execute(
        "UPDATE normalize_status SET status = 'pending', result_kind = NULL, result_id = NULL,"
        " lease_owner = 'other', lease_expires_at = now() + interval '1 hour'"
        " WHERE raw_id = (SELECT min(raw_id) FROM normalize_status)"
    )
    assert worker.poll(1) == []
    assert normalize_run(NORMALIZE, conn, "probe").claimed == 0

    # 임대가 만료된 pending은 집는다
    conn.execute("UPDATE normalize_status SET lease_expires_at = now() - interval '1 second'")
    assert worker.poll(1) != []
    assert normalize_run(NORMALIZE, conn, "probe").claimed == 1
    assert worker.poll(1) == []

    # failed는 이 명령이 다시 집지 않는다
    conn.execute(
        "UPDATE normalize_status SET status = 'failed', error_code = 'x', result_kind = NULL,"
        " result_id = NULL WHERE raw_id = (SELECT min(raw_id) FROM normalize_status)"
    )
    assert worker.poll(1) == []
    assert normalize_run(NORMALIZE, conn, "probe").claimed == 0


def test_ticketing_poll_agrees_with_what_run_creates(
    db: HiddenUrl, conn: psycopg.Connection
) -> None:
    worker = TicketingWorker(db)
    assert worker.poll(1) == []
    ingest_once(conn)
    NormalizeWorker(db, NORMALIZE).handle("batch")
    assert worker.poll(1) != []
    worker.handle(worker.poll(1)[0])
    assert q(conn, "SELECT count(*) AS n FROM tickets").fetchone()["n"] == 4
    assert worker.poll(1) == []


# 파이프 전체


def run_pipeline(
    config_dir: Path,
    resolve: Callable[[str], Any],
    ready: Callable[[], bool],
    stop: threading.Event | None = None,
) -> int:
    stop = stop or threading.Event()
    code: list[int] = []
    thread = threading.Thread(
        target=lambda: code.append(
            pipeline_main.main(
                [],
                config_dir=config_dir,
                stop_event=stop,
                resolve=resolve,
                probes=OK_PROBES,
                environ=ENV,
            )
        )
    )
    thread.start()
    deadline = time.monotonic() + WAIT
    try:
        while not ready():
            assert time.monotonic() < deadline, "파이프가 기대한 상태에 이르지 못했다"
            time.sleep(0.05)
    finally:
        stop.set()
        thread.join(WAIT)
    assert not thread.is_alive()
    return code[0]


def l2_resolver(
    db: str, vectors: MemoryVectorStore, l1: Callable[..., Any]
) -> Callable[[str], Any]:
    def resolve(path: str) -> Any:
        if path == "soc.l1.judge:build_worker":
            return lambda _c: L1Worker(db, 0.8, run=l1, clock=lambda: NOW)
        if path == "soc.l2.branch:build_worker":
            return lambda _c: branch_worker(db, vectors)
        if path == "soc.l2.analyze:build_worker":
            return lambda _c: L2AnalyzeWorker(
                db,
                ANALYZE,
                max_range_days=7,
                asset_statement_timeout_ms=5000,
                attack_version="20.0",
                run=analyze_run,
                clock=lambda: NOW,
            )
        return resolve_factory(path)  # 정규화·Ticket 생성은 진짜 파이프 워커

    return resolve


@pytest.fixture
def pipeline_dir(default_config_dir: Path, db: HiddenUrl, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("DATABASE_URL", str(db))
    (default_config_dir / "local.toml").write_text(FAST, encoding="utf-8")
    return default_config_dir


def test_raw_records_flow_to_an_incident_artifact_without_manual_steps(
    pipeline_dir: Path, db: HiddenUrl, conn: psycopg.Connection, reader_url: HiddenUrl
) -> None:
    ingest_once(conn)
    vectors = MemoryVectorStore()
    resolve = l2_resolver(str(db), vectors, l1_run(str(db)))

    def done() -> bool:
        # Ticket이 하나씩 붙을 때마다 재분석하므로, 4건이 모두 붙은 뒤의 분석이 끝나야 안정된다
        row = q(conn, "SELECT status, ticket_ids FROM incidents").fetchone()
        return (
            row is not None and row["status"] == "awaiting_review" and len(row["ticket_ids"]) == 4
        )

    assert run_pipeline(pipeline_dir, resolve, done) == 0
    first = counts(conn)
    assert first.pop("incident_artifacts") >= 1
    assert first == {"raw_records": 9, "alerts": 4, "events": 5, "tickets": 4, "incidents": 1}
    first = counts(conn)
    logs = q(conn, "SELECT count(*) AS n FROM agent_logs").fetchone()["n"]

    # 재기동해도 이미 처리된 건을 다시 처리하지 않는다
    assert run_pipeline(pipeline_dir, resolve, lambda: time.sleep(1.0) or True) == 0
    assert counts(conn) == first
    assert q(conn, "SELECT count(*) AS n FROM agent_logs").fetchone()["n"] == logs


def test_shutdown_leaves_in_flight_l1_work_waiting(
    pipeline_dir: Path, db: HiddenUrl, conn: psycopg.Connection, reader_url: HiddenUrl
) -> None:
    ingest_once(conn)
    stop = threading.Event()
    started = threading.Event()

    def blocked(task: Any) -> AgentResult:
        started.set()
        stop.wait(WAIT)  # 종료 신호가 오면 run_agent처럼 cancelled로 돌아온다
        return AgentResult(
            ok=False, output=None, failure="cancelled", detail=None, run_id=new_id("run")
        )

    resolve = l2_resolver(str(db), MemoryVectorStore(), blocked)
    assert run_pipeline(pipeline_dir, resolve, started.is_set, stop) == 0
    statuses = {r["status"] for r in q(conn, "SELECT status FROM tickets").fetchall()}
    assert statuses == {"new"}  # 실패·보류로 세지 않고 대기 상태 그대로다
    assert q(conn, "SELECT count(*) AS n FROM l1_attempts").fetchone()["n"] == 0
