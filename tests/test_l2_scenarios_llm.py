"""실제 LLM으로 L2 분류의 existing/new 판단을 사람이 확인한다(#356, llm 마커).

기본 실행과 CI에서는 돌지 않는다. 환경변수 LLM_API_KEY가 없으면 건너뛴다. AI 도구는 이 테스트를
실행하지 않는다. 비용이 든다.

실행: DATABASE_URL=… QDRANT_URL=… LLM_API_KEY=… SCENARIO_LLM_RUNS=10 \
  uv run pytest -m llm -s tests/test_l2_scenarios_llm.py
- 대상은 cases.json에서 `llm_manual`이 참인 케이스(1a, 1b, 5, 5b, 5c, 5d)다.
  후보가 없는 케이스는 LLM을 부르지 않는다.
- 케이스마다 SCENARIO_LLM_RUNS(기본 3, #362 기준은 10)번 임시 DB를 새로 채워 워커를 돌리고
  결과(판단, 기대값, 토큰 수)를 한 줄씩 낸다. -s로 보고 notes에 옮긴다.
  판단은 모델마다 달라 단언하지 않는다. 호출이 성공했는지만 본다.
- 모델 연결은 config/local.toml의 [llm](키는 환경변수 LLM_API_KEY)이다. 키 값은 출력하지 않는다.
- 도구는 테스트가 만든 임시 읽기 계정으로 임시 DB를 읽는다(tests/l1/test_l1_e2e_llm.py와 같은 방식)
"""

import os
import secrets
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from conftest import HiddenUrl
from psycopg import sql
from psycopg.conninfo import make_conninfo
from scenario_support import CASES, NOW, build_case

from soc.agent import AgentResult, run_agent
from soc.contracts import to_datetime
from soc.db.migrate import migrate
from soc.l2.branch.index import reindex
from soc.l2.branch.runtime import BranchService
from soc.l2.branch.worker import L2BranchWorker
from soc.l2.config import BranchSettings
from soc.store import BgeM3Embedder, VectorStore
from soc.store.config import load_config as load_store_config
from soc.store.config import read_settings as read_store_settings

pytestmark = pytest.mark.llm

READER = "soc_agent_reader"
SETTINGS = BranchSettings(candidate_window_ms=86_400_000, max_candidates=5, max_incident_tickets=10)
RUNS = int(os.environ.get("SCENARIO_LLM_RUNS", "3"))
MANUAL = [case for case in CASES if case.get("llm_manual")]


@pytest.fixture(autouse=True)
def _need_key() -> None:
    if not os.environ.get("LLM_API_KEY"):
        pytest.skip("환경변수 LLM_API_KEY가 없다")


@pytest.fixture
def reader(temp_database: HiddenUrl, monkeypatch: pytest.MonkeyPatch) -> Iterator[HiddenUrl]:
    """run_agent·도구가 임시 DB를 쓰게 환경변수를 바꾸고 읽기 계정을 만든다."""
    migrate(temp_database)
    name = f"soc_test_reader_{secrets.token_hex(4)}"
    password = secrets.token_urlsafe(16)
    with psycopg.connect(temp_database, autocommit=True) as admin:
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE {}").format(
                sql.Identifier(name), sql.Literal(password), sql.Identifier(READER)
            )
        )
    monkeypatch.setenv("DATABASE_URL", temp_database)  # run_agent가 Agent Log를 쓰는 곳
    monkeypatch.setenv(
        "AGENT_DATABASE_URL", make_conninfo(temp_database, user=name, password=password)
    )
    try:
        yield temp_database
    finally:
        with psycopg.connect(temp_database, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(name)))


@pytest.mark.parametrize("case", MANUAL, ids=lambda case: case["case"])
def test_real_model_decides_existing_or_new(reader: HiddenUrl, case: dict[str, Any]) -> None:
    results: list[AgentResult] = []
    store_settings = read_store_settings(load_store_config()["store"])
    embedder = BgeM3Embedder(store_settings.embedder)
    service = BranchService(embedder, VectorStore("test_branch_llm", embedder, store_settings))

    def recording_run(task: Any) -> AgentResult:
        result = run_agent(task)
        results.append(result)
        return result

    decisions = []
    for _ in range(RUNS):
        with psycopg.connect(reader, autocommit=True) as conn:
            conn.execute("TRUNCATE incidents, tickets, alerts, raw_records CASCADE")
            built = build_case(conn, case)
        reindex(reader, service, recreate=True)
        worker = L2BranchWorker(
            reader,
            SETTINGS,
            run=recording_run,
            clock=lambda: to_datetime(NOW),
            service=service,
        )
        worker.handle(built.current_ticket_id)
        result = results[-1]
        assert result.ok, result.failure
        decisions.append(result.output["decision"])
        print(  # noqa: T201 - 사람이 -s로 읽고 notes에 옮긴다
            f"[L2 시나리오] {case['case']} 판단={result.output['decision']} "
            f"기대={case['llm_expected']} 토큰={result.usage}"
        )

    print(f"[L2 시나리오] {case['case']} 요약 {decisions}")  # noqa: T201
