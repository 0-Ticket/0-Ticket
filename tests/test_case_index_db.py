"""승인된 Case 색인을 실제 PostgreSQL 샘플로 확인한다(#391, D-084, db 마커).

Qdrant는 qdrant-client의 메모리 모드와 가짜 임베더를 쓴다. 실제 Qdrant는 test_case_index_qdrant.py.
샘플: tests/fixtures/case_index/cases.json. Incident 1은 Artifact가 둘(1·3차), 2는 Artifact 없음,
3은 긴 필드, 4는 승인 대기이고 Case는 1~3만 있다. 샘플의 Case는 마이그레이션 뒤에 직접 넣으므로
대기 행이 없다(dev_seed처럼).
"""

import json
import shutil
import time
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fake_embedder import FakeEmbedder
from psycopg import errors, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
from qdrant_client import QdrantClient

from soc.api import ui_write
from soc.case_index import index
from soc.case_index.outbox import enqueue
from soc.case_index.source import PURPOSE, point_id
from soc.contracts import to_datetime
from soc.db.migrate import MIGRATIONS_DIR, migrate
from soc.store import CollectionMissing, StoreError, VectorStore
from soc.store.config import EmbedderSettings, QdrantSettings, StoreSettings

pytestmark = pytest.mark.db

SAMPLE = json.loads(
    (Path(__file__).parent / "fixtures" / "case_index" / "cases.json").read_text(encoding="utf-8")
)
SETTINGS = StoreSettings(
    qdrant=QdrantSettings(url_env="QDRANT_URL"),
    embedder=EmbedderSettings(model_id="m", revision="r"),
)
TIME_FIELDS = {"created_at", "updated_at", "confirmed_at"}
JSON_FIELDS = {"entities", "details", "timeline", "techniques"}
MIGRATION = "0310_case_index_jobs.sql"
READER = "soc_agent_reader"
CASE = {row["id"][-1]: row["id"] for row in SAMPLE["cases"]}
INC = {row["id"][-1]: row["id"] for row in SAMPLE["incidents"]}


class RecordingEmbedder(FakeEmbedder):
    """받은 문장을 모두 기록한다. 색인 텍스트에 무엇이 들어갔는지 본다."""

    def __init__(self) -> None:
        super().__init__()
        self.texts: list[str] = []

    def embed(self, text: str) -> list[float]:
        self.texts.append(text)
        return super().embed(text)


class Flaky:
    """upsert만 실패시키는 저장소 껍데기. error를 None으로 바꾸면 정상으로 돌아간다."""

    def __init__(self, store: VectorStore, error: Exception | None) -> None:
        self.store = store
        self.error = error

    def upsert(self, *args: Any) -> None:
        if self.error is not None:
            raise self.error
        self.store.upsert(*args)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.store, name)


def insert(conn: psycopg.Connection, table: str, data: dict[str, Any]) -> None:
    values = []
    for name, value in data.items():
        if name in TIME_FIELDS and value is not None:
            value = to_datetime(value)
        elif name in JSON_FIELDS and value is not None:
            value = Jsonb(value)
        values.append(value)
    conn.execute(
        sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
            sql.Identifier(table),
            sql.SQL(", ").join(map(sql.Identifier, data)),
            sql.SQL(", ").join(sql.Placeholder() * len(data)),
        ),
        values,
    )


def load_sample(url: str, tables: tuple[str, ...] = ("incidents", "incident_artifacts", "cases")):
    with psycopg.connect(url, autocommit=True) as conn:
        for table in tables:
            for row in SAMPLE[table]:
                insert(conn, table, row)


@pytest.fixture
def database(temp_database: str) -> str:
    migrate(temp_database)
    load_sample(temp_database)
    return temp_database


@pytest.fixture
def legacy_database(temp_database: str, tmp_path: Path) -> str:
    """0310만 빼고 적용한 DB. 마이그레이션 전 Case를 넣는 데 쓴다."""
    legacy_dir = tmp_path / "legacy_migrations"
    legacy_dir.mkdir()
    for migration in MIGRATIONS_DIR.glob("*.sql"):
        if migration.name != MIGRATION:
            shutil.copyfile(migration, legacy_dir / migration.name)
    migrate(temp_database, legacy_dir)
    return temp_database


def make_store(name: str = PURPOSE) -> VectorStore:
    return VectorStore(name, FakeEmbedder(), SETTINGS, client=QdrantClient(":memory:"))


def job(url: str, case_id: str) -> dict[str, Any] | None:
    with psycopg.connect(url, row_factory=dict_row) as conn:
        return conn.execute(
            "SELECT *, next_attempt_at - now() AS wait FROM case_index_jobs WHERE case_id = %s",
            (case_id,),
        ).fetchone()


def enqueue_all(url: str, *numbers: str) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        for number in numbers:
            enqueue(conn, CASE[number])


def make_due(url: str) -> None:
    """대기 행을 지금 바로 집을 수 있게 한다. DB 시각의 1초 전으로 둬서, 같은 DB 안의 연결끼리
    now()가 아주 조금 어긋나도(VM의 CPU 사이 시계 차이) 막 넣은 행이 빠지지 않게 한다."""
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute(
            "UPDATE case_index_jobs SET next_attempt_at = now() - interval '1 second' "
            "WHERE indexed_at IS NULL AND attempts = 0"
        )


def run_index(url: str, case_id: str, embedder: Any, store: Any) -> bool:
    with psycopg.connect(url, autocommit=True) as conn:
        return index.index_one(conn, case_id, embedder, store)


def point_ids(store: VectorStore) -> set[str]:
    return {hit.point_id for hit in store.search(FakeEmbedder().embed("x"), top_k=50)}


# 표와 마이그레이션


def test_migration_backfills_a_pending_job_for_each_existing_case(legacy_database: str) -> None:
    load_sample(legacy_database)

    migrate(legacy_database)

    for number in CASE:
        row = job(legacy_database, CASE[number])
        assert row is not None
        assert (row["indexed_at"], row["attempts"], row["last_error"]) == (None, 0, None)


def test_a_fresh_job_is_pending_and_due_now(database: str) -> None:
    enqueue_all(database, "1")
    row = job(database, CASE["1"])
    assert row["indexed_at"] is None and row["attempts"] == 0 and row["last_error"] is None
    assert row["next_attempt_at"] is not None and row["created_at"] is not None
    assert row["wait"].total_seconds() < 1  # DB 시각 기준. 막 넣은 행은 바로 집을 수 있다


def test_job_constraints_and_cascade(database: str) -> None:
    with psycopg.connect(database, autocommit=True) as conn:
        with pytest.raises(errors.ForeignKeyViolation):
            conn.execute(
                "INSERT INTO case_index_jobs (case_id) "
                "VALUES ('cas_01a19f93-1391-7000-8000-0000000000ff')"
            )
        enqueue(conn, CASE["1"])
        with pytest.raises(errors.CheckViolation):
            conn.execute("UPDATE case_index_jobs SET attempts = -1")
        conn.execute("DELETE FROM cases WHERE id = %s", (CASE["1"],))
        assert conn.execute("SELECT count(*) FROM case_index_jobs").fetchone() == (0,)


def test_agent_reader_cannot_read_the_jobs(database: str) -> None:
    enqueue_all(database, "1")
    with psycopg.connect(database, autocommit=True) as conn:
        assert conn.execute(
            "SELECT has_any_column_privilege(%s, 'case_index_jobs', 'SELECT')", (READER,)
        ).fetchone() == (False,)
        conn.execute(f"SET ROLE {READER}")
        try:
            with pytest.raises(errors.InsufficientPrivilege):
                conn.execute("SELECT 1 FROM case_index_jobs")
        finally:
            conn.execute("RESET ROLE")


def test_enqueue_is_idempotent(database: str) -> None:
    enqueue_all(database, "1")
    run_index(database, CASE["1"], FakeEmbedder(), make_store())
    done = job(database, CASE["1"])["indexed_at"]
    enqueue_all(database, "1")  # 이미 색인한 Case를 다시 대기로 돌리지 않는다
    assert job(database, CASE["1"])["indexed_at"] == done


# 색인 한 건


def test_index_one_uses_the_latest_artifact_and_writes_an_empty_payload_point(
    database: str,
) -> None:
    with psycopg.connect(database, autocommit=True) as conn:
        # 사람이 쓴 반려 사유가 있어도 색인 텍스트에는 들어가지 않는다
        conn.execute(
            "INSERT INTO incident_reviews (incident_id, decision, reason, decided_by, "
            "review_round, analysis_round) "
            "VALUES (%s, 'reject', 'REJECT-REASON-MARKER', 'u', 1, 1)",
            (INC["1"],),
        )
    enqueue_all(database, "1")
    embedder, store = RecordingEmbedder(), make_store()

    assert run_index(database, CASE["1"], embedder, store) is True

    (text,) = embedder.texts
    assert text == (
        "title: Web shell on example web server\n"
        "summary: Attacker uploaded a web shell through the upload form\n"
        "cause: Unrestricted file upload was abused\n"
        "impact: The web server executed attacker supplied code\n"
        "further_risk: The same upload path can drop more tools\n"
        "technique: Web Shell\n"
        "technique: Exploit Public-Facing Application"
    )
    for forbidden in ("OLD-ROUND-ONE", "REJECT-REASON-MARKER", "TIMELINE-MARKER", "192.0.2.77"):
        assert forbidden not in text
    hits = store.search(FakeEmbedder().embed(text), top_k=5)
    assert [(hit.point_id, hit.payload) for hit in hits] == [(point_id(CASE["1"]), {})]
    assert hits[0].score == pytest.approx(1.0)
    row = job(database, CASE["1"])
    assert row["indexed_at"] is not None and row["last_error"] is None


def test_a_second_run_does_not_embed_or_write_again(database: str) -> None:
    enqueue_all(database, "1")
    embedder, store = RecordingEmbedder(), make_store()
    assert run_index(database, CASE["1"], embedder, store) is True
    assert run_index(database, CASE["1"], embedder, store) is False
    assert len(embedder.texts) == 1 and point_ids(store) == {point_id(CASE["1"])}


def test_a_case_without_an_artifact_is_indexed_with_its_title_only(database: str) -> None:
    enqueue_all(database, "2")
    embedder, store = RecordingEmbedder(), make_store()
    assert run_index(database, CASE["2"], embedder, store) is True
    assert embedder.texts == ["title: Suspicious login burst"]
    assert point_ids(store) == {point_id(CASE["2"])}


def test_a_long_case_is_cut_by_the_planned_limits(database: str) -> None:
    enqueue_all(database, "3")
    embedder = RecordingEmbedder()
    run_index(database, CASE["3"], embedder, make_store())
    (text,) = embedder.texts
    assert len(text) <= 6000
    assert sum(line.startswith("technique: ") for line in text.split("\n")) == 10


def test_a_missing_case_or_job_is_not_indexed(database: str) -> None:
    store = make_store()
    assert run_index(database, CASE["1"], FakeEmbedder(), store) is False  # 대기 행 없음
    assert not store.exists()


def test_the_collection_is_created_on_the_first_write(database: str) -> None:
    enqueue_all(database, "1")
    store = make_store()
    assert not store.exists()
    run_index(database, CASE["1"], FakeEmbedder(), store)
    assert store.exists()


# 실패와 재시도


def test_a_failure_records_the_class_name_and_backs_off_thirty_then_sixty_seconds(
    database: str,
) -> None:
    enqueue_all(database, "1")
    store = Flaky(make_store(), StoreError("http://qdrant.example:6333 SECRET-TITLE"))

    with pytest.raises(StoreError):
        run_index(database, CASE["1"], FakeEmbedder(), store)

    row = job(database, CASE["1"])
    assert (row["indexed_at"], row["attempts"], row["last_error"]) == (None, 1, "StoreError")
    assert 25 < row["wait"].total_seconds() <= 30

    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute("UPDATE case_index_jobs SET next_attempt_at = now() - interval '1 second'")
    with pytest.raises(StoreError):
        run_index(database, CASE["1"], FakeEmbedder(), store)
    row = job(database, CASE["1"])
    assert row["attempts"] == 2 and 55 < row["wait"].total_seconds() <= 60
    assert "qdrant.example" not in str(row) and "SECRET" not in str(row)


def test_poll_skips_a_job_until_its_backoff_has_passed(database: str) -> None:
    enqueue_all(database, "1", "2")
    make_due(database)
    worker = index.CaseIndexWorker(database, SETTINGS)
    with pytest.raises(StoreError):
        run_index(database, CASE["1"], FakeEmbedder(), Flaky(make_store(), StoreError()))
    assert worker.poll(10) == [CASE["2"]]

    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute(
            "UPDATE case_index_jobs SET next_attempt_at = now() - interval '1 second' "
            "WHERE case_id = %s",
            (CASE["1"],),
        )
    assert worker.poll(10) == [CASE["1"], CASE["2"]]


@pytest.mark.parametrize("skew", [300_000_000, -300_000_000])
def test_due_time_and_backoff_come_only_from_the_database_clock(
    database: str, monkeypatch: pytest.MonkeyPatch, skew: int
) -> None:
    """호스트(파이썬) 시계가 ±약 10년 어긋나도 poll 조건과 백오프가 같다. 시각은 DB now()뿐이다."""
    real = time.time
    monkeypatch.setattr(time, "time", lambda: real() + skew)
    enqueue_all(database, "1", "2")
    make_due(database)
    worker = index.CaseIndexWorker(database, SETTINGS)
    assert worker.poll(10) == [CASE["1"], CASE["2"]]

    with pytest.raises(StoreError):
        run_index(database, CASE["1"], FakeEmbedder(), Flaky(make_store(), StoreError()))

    row = job(database, CASE["1"])
    assert 25 < row["wait"].total_seconds() <= 30
    assert worker.poll(10) == [CASE["2"]]


def test_the_case_is_indexed_when_qdrant_comes_back_and_the_error_is_cleared(
    database: str,
) -> None:
    enqueue_all(database, "1")
    store = Flaky(make_store(), StoreError())
    with pytest.raises(StoreError):
        run_index(database, CASE["1"], FakeEmbedder(), store)
    with psycopg.connect(database, autocommit=True) as conn:
        conn.execute("UPDATE case_index_jobs SET next_attempt_at = now() - interval '1 second'")

    store.error = None
    assert run_index(database, CASE["1"], FakeEmbedder(), store) is True

    row = job(database, CASE["1"])
    assert row["indexed_at"] is not None and row["last_error"] is None and row["attempts"] == 1
    assert point_ids(store.store) == {point_id(CASE["1"])}


def test_a_collection_missing_error_is_not_a_failure(database: str) -> None:
    enqueue_all(database, "1")
    store = make_store()
    with pytest.raises(CollectionMissing):  # 메모리 모드도 컬렉션 없음을 같은 오류로 낸다
        store.upsert(point_id(CASE["1"]), FakeEmbedder().embed("x"), {})
    assert run_index(database, CASE["1"], FakeEmbedder(), store) is True
    assert job(database, CASE["1"])["attempts"] == 0


# 워커


def test_worker_polls_pending_jobs_in_order_up_to_the_limit(database: str) -> None:
    enqueue_all(database, "3", "1", "2")  # 문장마다 created_at이 달라 등록한 순서가 된다
    make_due(database)
    worker = index.CaseIndexWorker(database, SETTINGS)
    assert worker.poll(2) == [CASE["3"], CASE["1"]]
    assert worker.poll(10) == [CASE["3"], CASE["1"], CASE["2"]]
    with pytest.raises(ValueError):
        worker.poll(0)


def test_worker_handle_indexes_with_the_injected_resources_and_leaves_done_jobs_alone(
    database: str,
) -> None:
    enqueue_all(database, "1", "2")
    make_due(database)
    store = make_store()
    worker = index.CaseIndexWorker(database, SETTINGS, embedder=FakeEmbedder(), store=store)

    for case_id in worker.poll(10):
        worker.handle(case_id)

    assert point_ids(store) == {point_id(CASE["1"]), point_id(CASE["2"])}
    assert worker.poll(10) == []


def test_worker_handle_raises_on_failure_so_the_executor_counts_it(database: str) -> None:
    enqueue_all(database, "1")
    worker = index.CaseIndexWorker(
        database, SETTINGS, embedder=FakeEmbedder(), store=Flaky(make_store(), StoreError())
    )
    with pytest.raises(StoreError):
        worker.handle(CASE["1"])


def test_a_failure_to_build_the_embedder_or_store_is_recorded_and_backs_off(
    database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """QDRANT_URL이 없는 것처럼 자원을 만들지 못해도 대기 행에 남고 백오프한다."""
    enqueue_all(database, "1")

    def broken(settings: Any) -> Any:
        raise StoreError("http://qdrant.example:6333 SECRET-TITLE")

    monkeypatch.setattr(index, "get_embedder", broken)
    worker = index.CaseIndexWorker(database, SETTINGS)

    with pytest.raises(StoreError):
        worker.handle(CASE["1"])

    row = job(database, CASE["1"])
    assert (row["indexed_at"], row["attempts"], row["last_error"]) == (None, 1, "StoreError")
    assert 25 < row["wait"].total_seconds() <= 30
    assert worker.poll(10) == []
    assert "qdrant.example" not in str(row) and "SECRET" not in str(row)


# 승인에서 색인까지


def test_approval_leaves_a_job_in_the_same_transaction_and_the_worker_indexes_it(
    database: str,
) -> None:
    with psycopg.connect(database, row_factory=dict_row, autocommit=True) as conn:
        result = ui_write.approve_incident(conn, INC["4"], "tester")
    case_id = result["case_id"]
    row = job(database, case_id)
    assert row is not None and row["indexed_at"] is None and row["attempts"] == 0
    make_due(database)

    embedder, store = RecordingEmbedder(), make_store()
    worker = index.CaseIndexWorker(database, SETTINGS, embedder=embedder, store=store)
    assert worker.poll(10) == [case_id]
    worker.handle(case_id)

    assert point_ids(store) == {point_id(case_id)}
    assert "cause: Input from the login form reached a SQL query unescaped" in embedder.texts[0]


def test_a_failing_job_insert_rolls_the_approval_back(
    database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(conn: Any, case_id: str) -> None:
        raise RuntimeError

    monkeypatch.setattr(ui_write, "enqueue", broken)
    with psycopg.connect(database, row_factory=dict_row, autocommit=True) as conn:
        with pytest.raises(RuntimeError):
            ui_write.approve_incident(conn, INC["4"], "tester")
        status = conn.execute("SELECT status FROM incidents WHERE id = %s", (INC["4"],)).fetchone()
        assert status["status"] == "awaiting_review"
        assert conn.execute("SELECT count(*) AS n FROM cases").fetchone()["n"] == 3
        assert conn.execute("SELECT count(*) AS n FROM incident_reviews").fetchone()["n"] == 0


def test_rejection_leaves_no_job(database: str) -> None:
    with psycopg.connect(database, row_factory=dict_row, autocommit=True) as conn:
        ui_write.reject_incident(conn, INC["4"], "tester", "needs more work")
        assert conn.execute("SELECT count(*) AS n FROM case_index_jobs").fetchone()["n"] == 0


# 재색인과 점검


def test_check_counts_each_kind_of_gap(database: str) -> None:
    store = make_store()
    assert index.check(database, store) == {
        "cases": 3,
        "missing": 0,
        "no_job": 3,
        "pending": 0,
        "no_artifact": 1,
    }

    enqueue_all(database, "1", "2", "3")
    assert index.check(database, store) == {
        "cases": 3,
        "missing": 0,
        "no_job": 0,
        "pending": 3,
        "no_artifact": 1,
    }

    for number in CASE:
        run_index(database, CASE[number], FakeEmbedder(), store)
    assert index.check(database, store) == {
        "cases": 3,
        "missing": 0,
        "no_job": 0,
        "pending": 0,
        "no_artifact": 1,
    }


def test_check_reports_an_indexed_case_whose_point_is_gone_as_missing(database: str) -> None:
    store = make_store()
    enqueue_all(database, "1", "2")
    for number in ("1", "2"):
        run_index(database, CASE[number], FakeEmbedder(), store)
    store._client.delete(store.collection, points_selector=[point_id(CASE["1"])])

    counts = index.check(database, store)

    assert counts["missing"] == 1 and counts["pending"] == 0 and counts["no_job"] == 1


def test_check_treats_a_missing_collection_as_missing_for_indexed_cases(database: str) -> None:
    store = make_store()
    enqueue_all(database, "1")
    run_index(database, CASE["1"], FakeEmbedder(), store)
    store.drop_collection()
    assert index.check(database, store)["missing"] == 1


def test_reindex_creates_missing_jobs_and_indexes_every_case(database: str) -> None:
    store = make_store()

    counts = index.reindex(database, FakeEmbedder(), store)

    assert counts == {"processed": 3, "succeeded": 3, "failed": 0}
    assert point_ids(store) == {point_id(c) for c in CASE.values()}
    assert index.check(database, store)["no_job"] == 0
    assert index.check(database, store)["pending"] == 0
    assert index.check(database, store)["missing"] == 0


def test_reindex_refills_a_lost_point_without_recreating(database: str) -> None:
    store = make_store()
    index.reindex(database, FakeEmbedder(), store)
    store._client.delete(store.collection, points_selector=[point_id(CASE["2"])])
    assert index.check(database, store)["missing"] == 1

    assert index.reindex(database, FakeEmbedder(), store)["failed"] == 0

    assert index.check(database, store)["missing"] == 0


def test_reindex_recreate_drops_the_collection_and_fills_it_again(database: str) -> None:
    store = make_store()
    index.reindex(database, FakeEmbedder(), store)
    store._client.delete(store.collection, points_selector=[point_id(CASE["1"])])

    counts = index.reindex(database, FakeEmbedder(), store, recreate=True)

    assert counts == {"processed": 3, "succeeded": 3, "failed": 0}
    assert point_ids(store) == {point_id(c) for c in CASE.values()}
    assert index.check(database, store)["missing"] == 0


def test_reindex_counts_failures_and_keeps_going_and_ignores_backoff(database: str) -> None:
    enqueue_all(database, "1")
    with pytest.raises(StoreError):
        run_index(database, CASE["1"], FakeEmbedder(), Flaky(make_store(), StoreError()))
    store = Flaky(make_store(), StoreError())

    counts = index.reindex(database, FakeEmbedder(), store)

    assert counts == {"processed": 3, "succeeded": 0, "failed": 3}
    store.error = None
    counts = index.reindex(database, FakeEmbedder(), store)  # 백오프 중이어도 운영자가 다시 돌린다
    assert counts == {"processed": 3, "succeeded": 3, "failed": 0}
