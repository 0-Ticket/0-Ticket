"""실제 LLM으로 가설 생성 run 1건과 검증 run 1건(#389, llm 마커). 기본 실행과 CI에서는 돌지 않는다.

손으로 만든 샘플 뉴스(tests/fixtures/l3_hunt/actor_news.json)와 가짜 행위자(tests/fixtures/l3_intel/
attack.json)를 임시 DB에 넣고, 가설 생성 run이 get_attack_actor를 부르는지와 검증 run이 부르는지를
Agent Log로 센다. 결과 값은 모델마다 달라 단언하지 않고 출력 계약 통과와 Agent Log만 본다.

실행: DATABASE_URL=… LLM_API_KEY=… uv run pytest -m llm -s tests/test_l3_hunt_actor_llm.py
- 모델 연결은 config/local.toml의 [llm](키는 환경변수 LLM_API_KEY)을 쓴다
- 실제 호출 비용이 든다(가설 생성 1번, 검증 최대 1번, 각각 최대 [agent.l3] max_turns 턴)
- -s로 돌리면 도구 호출 수와 부른 이름, 근거·모델 단독 기법 수가 한 줄로 나온다(건수만, 본문 없음)
"""

import json
import secrets
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import psycopg
import pytest
from conftest import HiddenUrl
from psycopg import sql
from psycopg.conninfo import make_conninfo

from soc.agent import run_agent
from soc.db.migrate import migrate
from soc.l3.config import load_config
from soc.l3.hunt.hypothesize import ACTOR_TOOL, hypothesize
from soc.l3.hunt.settings import read_hunt_settings
from soc.l3.hunt.verify import HuntVerifier
from soc.l3.intel import parse, store

pytestmark = pytest.mark.llm

READER = "soc_agent_reader"
FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def seeded(temp_database: HiddenUrl, monkeypatch: pytest.MonkeyPatch) -> Iterator[HiddenUrl]:
    migrate(temp_database)
    name = f"soc_test_reader_{secrets.token_hex(4)}"
    password = secrets.token_urlsafe(16)
    now = datetime.now(UTC)
    attack, actors = parse.parse_attack_bundle(
        (FIXTURES / "l3_intel" / "attack.json").read_bytes(), version="20.0"
    )
    news = json.loads((FIXTURES / "l3_hunt" / "actor_news.json").read_text(encoding="utf-8"))
    with psycopg.connect(temp_database, autocommit=True) as admin:
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE {}").format(
                sql.Identifier(name), sql.Literal(password), sql.Identifier(READER)
            )
        )
        store.save_attack(admin, "20.0", attack, now=now)
        store.save_attack_actors(admin, "20.0", actors, now=now)
        for item in news["news"]:
            admin.execute(
                "INSERT INTO threat_news (source, kind, source_ref, title, summary, link,"
                " published_at, fetched_at, updated_at)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    item["source"],
                    item["kind"],
                    item["source_ref"],
                    item["title"],
                    item["summary"],
                    item["source_ref"],
                    now - timedelta(hours=item["hours_ago"]),
                    now,
                    now,
                ),
            )
    monkeypatch.setenv("DATABASE_URL", temp_database)
    monkeypatch.setenv(
        "AGENT_DATABASE_URL", make_conninfo(temp_database, user=name, password=password)
    )
    try:
        yield temp_database
    finally:
        with psycopg.connect(temp_database, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(name)))


def tool_calls(conn: psycopg.Connection, run_id: str) -> list[str]:
    """그 run이 이 도구에 넘긴 이름(입력의 name). 기록용이고 근거 판단은 결과로 한다."""
    rows = conn.execute(
        "SELECT input FROM agent_logs WHERE run_id = %s AND kind = 'tool' AND name = %s"
        " ORDER BY seq",
        (run_id, ACTOR_TOOL),
    ).fetchall()
    return [str(r[0].get("name")) if isinstance(r[0], dict) else "?" for r in rows]


def test_real_model_hypothesizes_with_the_actor_tool_and_verify_is_observed(
    seeded: HiddenUrl,
) -> None:
    settings = read_hunt_settings(load_config()["l3"])
    with psycopg.connect(seeded, autocommit=True) as conn:
        result = hypothesize(conn, settings, run=run_agent, now=datetime.now(UTC))
        assert result.failure is None, result.failure  # 실패 종류만 보인다
        generate_calls = tool_calls(conn, _run_id(conn, result.hunt_run_id))
        details = [
            row[0]
            for row in conn.execute(
                "SELECT details FROM hunts WHERE hunt_run_id = %s", (result.hunt_run_id,)
            )
        ]
    basis = [d["sources"].get("attack_basis") for d in details]
    print(  # noqa: T201
        f"가설 생성: 도구 호출 {len(generate_calls)}번, 부른 이름 {generate_calls},"
        f" 가설 {len(details)}건, attack_basis {basis}"
    )
    if not result.saved:
        return

    HuntVerifier(seeded, settings).handle(result.saved[0])  # 기본 실행 함수는 run_agent

    with psycopg.connect(seeded) as conn:
        verify_run = conn.execute(
            "SELECT run_id FROM agent_logs WHERE subject_id = %s AND details->>'task' = 'l3_verify'"
            " ORDER BY started_at LIMIT 1",
            (result.saved[0],),
        ).fetchone()
        verify_calls = [] if verify_run is None else tool_calls(conn, verify_run[0])
    print(f"검증: 도구 호출 {len(verify_calls)}번, 부른 이름 {verify_calls}")  # noqa: T201


def _run_id(conn: psycopg.Connection, hunt_run_id: str) -> str:
    row = conn.execute(
        "SELECT run_id FROM agent_logs WHERE subject_id = %s ORDER BY started_at LIMIT 1",
        (hunt_run_id,),
    ).fetchone()
    assert row is not None
    return row[0]
