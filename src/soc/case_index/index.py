"""승인된 Case를 `confirmed_cases` 컬렉션에 색인하는 워커와 점검·재색인(#391, D-084).

Case는 승인 시점 복사본이고 텍스트는 불변이다. 그래서 대기 행에 revision이 없고, 같은 Case의 동시
쓰기를 막는 잠금도 두지 않는다(같은 텍스트·같은 point ID의 upsert는 멱등이다). Qdrant 쓰기는
PostgreSQL 트랜잭션에 묶지 않는다. 실패는 `case_index_jobs`에 예외 클래스 이름만 남기고 백오프로
다시 시도하며 포기하지 않는다. 로그·출력에는 건수와 예외 이름만 남긴다. Case 제목·요약·Artifact
문장과 Qdrant 주소는 남기지 않는다.
"""

import os
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import psycopg
from psycopg.rows import dict_row

from soc.case_index.source import LATEST_ARTIFACT_SQL, PURPOSE, point_id
from soc.case_index.text import case_text
from soc.l2.branch.runtime import get_service
from soc.store import CollectionMissing, VectorStore
from soc.store.config import read_settings

BACKOFF_START_SECONDS = 30
BACKOFF_MAX_SECONDS = 600
_ARTIFACT_COLUMNS = "cause, impact, further_risk, techniques"


def backoff_seconds(attempts: int) -> int:
    """실패 n번째 뒤의 대기 시간. 30초에서 시작해 두 배씩 늘고 10분을 넘지 않는다."""
    return min(BACKOFF_START_SECONDS * 2 ** min(max(attempts, 1) - 1, 10), BACKOFF_MAX_SECONDS)


def get_embedder(settings: Any) -> Any:
    """분류 색인 워커와 같은 임베더 인스턴스를 쓴다. 상주 모델을 늘리지 않는다(2.27GB, D-044)."""
    return get_service(settings).embedder


@lru_cache(maxsize=1)
def get_store(settings: Any) -> VectorStore:
    return VectorStore(PURPOSE, get_embedder(settings), settings)


def read_case(conn: psycopg.Connection, case_id: str) -> tuple[str, str | None, dict | None] | None:
    """(제목, 요약, 승인 당시 Artifact 또는 None). Case가 없으면 None."""
    with conn.cursor(row_factory=dict_row) as cursor:
        case = cursor.execute(
            "SELECT title, summary, incident_id FROM cases WHERE id = %s", (case_id,)
        ).fetchone()
        if case is None:
            return None
        artifact = cursor.execute(
            LATEST_ARTIFACT_SQL.format(columns=_ARTIFACT_COLUMNS), (case["incident_id"],)
        ).fetchone()
    return case["title"], case["summary"], artifact


def record_failure(conn: psycopg.Connection, case_id: str, error: Exception) -> None:
    """대기 행에 시도 횟수·예외 클래스 이름·다음 시도 시각을 남긴다. 메시지는 남기지 않는다."""
    with conn.transaction():
        row = conn.execute(
            "UPDATE case_index_jobs SET attempts = attempts + 1, last_error = %s "
            "WHERE case_id = %s AND indexed_at IS NULL RETURNING attempts",
            (type(error).__name__, case_id),
        ).fetchone()
        if row is not None:
            conn.execute(
                "UPDATE case_index_jobs "
                "SET next_attempt_at = now() + make_interval(secs => %s) WHERE case_id = %s",
                (backoff_seconds(row[0]), case_id),
            )


def index_one(conn: psycopg.Connection, case_id: str, embedder: Any, store: Any) -> bool:
    """대기 중인 Case 하나를 색인한다. 색인했으면 True, 할 일이 없으면 False.

    실패하면 대기 행에 시도 횟수·예외 클래스 이름·다음 시도 시각을 남기고 예외를 다시 올린다.
    """
    if (
        conn.execute(
            "SELECT 1 FROM case_index_jobs WHERE case_id = %s AND indexed_at IS NULL", (case_id,)
        ).fetchone()
        is None
    ):
        return False
    try:
        case = read_case(conn, case_id)
        if case is None:
            return False
        vector = embedder.embed(case_text(*case))
        point = point_id(case_id)
        try:
            store.upsert(point, vector, {})
        except CollectionMissing:
            store.ensure_collection()
            store.upsert(point, vector, {})
        conn.execute(
            "UPDATE case_index_jobs SET indexed_at = now(), last_error = NULL WHERE case_id = %s",
            (case_id,),
        )
        return True
    except Exception as exc:
        record_failure(conn, case_id, exc)
        raise


@dataclass(frozen=True)
class CaseIndexWorker:
    """l2 단계 워커. embedder·store를 주지 않으면 처음 쓸 때 분류 서비스의 임베더로 만든다."""

    database_url: str
    settings: Any
    embedder: Any = None
    store: Any = None

    stage = "l2"
    name = "case_index"

    def poll(self, limit: int) -> list[str]:
        if type(limit) is not int or limit < 1:
            raise ValueError("limit은 양의 정수다")
        with psycopg.connect(self.database_url, autocommit=True) as conn:
            rows = conn.execute(
                "SELECT case_id FROM case_index_jobs "
                "WHERE indexed_at IS NULL AND next_attempt_at <= now() "
                "ORDER BY created_at, case_id LIMIT %s",
                (limit,),
            ).fetchall()
        return [row[0] for row in rows]

    def handle(self, case_id: str) -> None:
        with psycopg.connect(self.database_url, autocommit=True) as conn:
            try:
                embedder = (
                    self.embedder if self.embedder is not None else get_embedder(self.settings)
                )
                store = self.store if self.store is not None else get_store(self.settings)
            except (
                Exception
            ) as exc:  # 자원을 못 만들어도(QDRANT_URL 없음 등) 백오프를 건너뛰지 않는다
                record_failure(conn, case_id, exc)
                raise
            index_one(conn, case_id, embedder, store)


def build_worker(config: dict[str, Any]) -> CaseIndexWorker:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL이 필요하다")
    return CaseIndexWorker(database_url, read_settings(config["store"]))


def reindex(
    database_url: str, embedder: Any, store: Any, *, recreate: bool = False
) -> dict[str, int]:
    """모든 Case를 다시 색인하고 처리·성공·실패 건수를 돌려준다. 백오프는 무시한다.

    대기 행이 없는 Case(마이그레이션 뒤에 직접 넣은 것)는 행을 만든다. 모든 행을 대기로 되돌려
    순서대로 색인하므로 잃어버린 point도 다시 채운다. recreate면 컬렉션을 지우고 시작한다.
    """
    if recreate and store.exists():
        store.drop_collection()
    store.ensure_collection()
    counts = {"processed": 0, "succeeded": 0, "failed": 0}
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute(
            "INSERT INTO case_index_jobs (case_id) SELECT id FROM cases "
            "ON CONFLICT (case_id) DO NOTHING"
        )
        conn.execute(
            "UPDATE case_index_jobs SET indexed_at = NULL, attempts = 0, last_error = NULL, "
            "next_attempt_at = now()"
        )
        ids = [row[0] for row in conn.execute("SELECT id FROM cases ORDER BY id").fetchall()]
        for case_id in ids:
            counts["processed"] += 1
            try:
                index_one(conn, case_id, embedder, store)
            except Exception:
                counts["failed"] += 1
            else:
                counts["succeeded"] += 1
    return counts


def check(database_url: str, store: Any) -> dict[str, int]:
    """Case와 대기 행·Qdrant point를 전수 대조한다.

    missing: 색인했다고 기록됐는데 point가 없다. no_job: 대기 행이 없다. pending: 아직 색인 전이다.
    no_artifact: 승인 당시 Artifact가 없다(정보 표시. 제목·요약만으로 색인된다).
    """
    counts = {"cases": 0, "missing": 0, "no_job": 0, "pending": 0, "no_artifact": 0}
    with psycopg.connect(database_url, autocommit=True) as conn:
        rows = conn.execute(
            "SELECT c.id, j.case_id IS NOT NULL, j.indexed_at IS NOT NULL, "
            "NOT EXISTS (SELECT 1 FROM incident_artifacts a WHERE a.incident_id = c.incident_id) "
            "FROM cases c LEFT JOIN case_index_jobs j ON j.case_id = c.id ORDER BY c.id"
        ).fetchall()
    collection_exists = store.exists()
    for case_id, has_job, indexed, no_artifact in rows:
        counts["cases"] += 1
        counts["no_artifact"] += no_artifact
        if not has_job:
            counts["no_job"] += 1
        elif not indexed:
            counts["pending"] += 1
        elif not collection_exists or store.point_payload(point_id(case_id)) is None:
            counts["missing"] += 1
    return counts
