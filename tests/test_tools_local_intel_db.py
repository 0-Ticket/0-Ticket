"""로컬 ATT&CK·KEV 조회 도구를 실제 PostgreSQL과 읽기 역할로 확인한다(#311, db 마커).

임시 DB에 마이그레이션을 적용하고 tests/fixtures/l3_intel/의 손으로 줄인 ATT&CK·KEV 샘플을
수집 코드(parse → store)로 넣는다. 도구는 테스트가 만든 임시 LOGIN 역할(soc_agent_reader 멤버,
임의 비밀번호, 끝나면 삭제)로 접속한다.
"""

import asyncio
import secrets
import socket
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import psycopg
import pytest
from conftest import HiddenUrl
from psycopg import sql
from psycopg.conninfo import make_conninfo
from test_agent_core import CONFIG
from tool_helpers import Caller, parse

from soc.db.migrate import migrate
from soc.l3.intel import parse as intel_parse
from soc.l3.intel import store
from soc.tools import default_registry

pytestmark = pytest.mark.db

FIXTURES = Path(__file__).parent / "fixtures" / "l3_intel"
NOW = datetime(2026, 11, 13, 1, 0, tzinfo=UTC)
READER = "soc_agent_reader"
NAMES = ["get_attack_technique", "search_attack_techniques", "get_cve"]
LOCAL_INTEL = {"attack_version": "20.0", "description_max_chars": 600, "list_max_items": 20}


def config(**local_intel: Any) -> dict[str, Any]:
    tools = {
        **CONFIG["tools"],
        "allowed": {"l2": NAMES, "l3": NAMES},
        "local_intel": {**LOCAL_INTEL, **local_intel},
    }
    return {**CONFIG, "tools": tools}


def run_tool(name: str, arguments: dict[str, Any], cfg: dict[str, Any] | None = None) -> dict:
    caller = Caller(default_registry(), cfg or config(), stage="l2")
    return parse(asyncio.run(caller(name, arguments)))


def collect_fixtures(url: str) -> None:
    attack = intel_parse.parse_attack((FIXTURES / "attack.json").read_bytes(), version="20.0")
    catalog = intel_parse.parse_kev_catalog(
        (FIXTURES / "kev.json").read_bytes(), summary_max_chars=1000
    )
    # 샘플에 없는 상위 기법(T1059)과 하위 기법(T1059.001)은 손으로 더한다
    attack += [
        intel_parse.Technique(
            "T1059",
            "Command and Scripting Interpreter",
            ("execution",),
            "Adversaries abuse command and scripting interpreters, such as a shell.",
        ),
        intel_parse.Technique("T1059.001", "PowerShell", ("execution",), "PowerShell commands."),
    ]
    with psycopg.connect(url, autocommit=True) as conn:
        store.save_attack(conn, "20.0", attack, now=NOW)
        store.save_kev(conn, source="cisa_kev", catalog=catalog, now=NOW)


@pytest.fixture
def migrated(temp_database: HiddenUrl) -> HiddenUrl:
    migrate(temp_database)
    return temp_database


@pytest.fixture
def reader_url(migrated: HiddenUrl, monkeypatch: pytest.MonkeyPatch) -> Iterator[HiddenUrl]:
    """soc_agent_reader 멤버인 임시 LOGIN 역할. 비밀번호는 임의 값이고 끝나면 역할을 지운다."""
    name = f"soc_test_reader_{secrets.token_hex(4)}"
    password = secrets.token_urlsafe(16)
    with psycopg.connect(migrated, autocommit=True) as admin:
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} IN ROLE {}").format(
                sql.Identifier(name), sql.Literal(password), sql.Identifier(READER)
            )
        )
    url = HiddenUrl(make_conninfo(migrated, user=name, password=password))
    monkeypatch.setenv("AGENT_DATABASE_URL", url)
    try:
        yield url
    finally:
        with psycopg.connect(migrated, autocommit=True) as admin:
            admin.execute(sql.SQL("DROP ROLE IF EXISTS {}").format(sql.Identifier(name)))


@pytest.fixture
def loaded(migrated: HiddenUrl, reader_url: HiddenUrl) -> HiddenUrl:
    collect_fixtures(migrated)
    return reader_url


# 읽기 역할(마이그레이션 0302)


def test_reader_can_read_intel_tables_but_not_news(loaded: str) -> None:
    with psycopg.connect(loaded) as conn:
        assert conn.execute("SELECT count(*) FROM attack_techniques").fetchone() == (4,)
        assert conn.execute("SELECT count(*) FROM kev_entries").fetchone() == (3,)
        assert conn.execute("SELECT count(*) FROM intel_source_state").fetchone() == (1,)


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT count(*) FROM threat_news",
        "UPDATE attack_techniques SET name = 'x'",
        "DELETE FROM kev_entries",
        "INSERT INTO intel_source_state (source, catalog_version, collected_at)"
        " VALUES ('x', 'v', now())",
    ],
)
def test_reader_is_denied_news_and_writes(loaded: str, statement: str) -> None:
    with psycopg.connect(loaded) as conn, pytest.raises(psycopg.errors.InsufficientPrivilege):
        conn.execute(statement)


# 도구


def test_technique_input_forms_read_the_same_row(loaded: str) -> None:
    bodies = []
    for value in ("T1190", "attack.T1190", "attack.t1190"):
        body = run_tool("get_attack_technique", {"technique_id": value})
        bodies.append({k: v for k, v in body.items() if k != "call_id"})
    assert bodies[0] == bodies[1] == bodies[2]
    body = bodies[0]
    assert body["status"] == "found"
    assert body["name"] == "Exploit Public-Facing Application"
    assert body["tactics"] == ["initial-access"]
    assert body["detection_sources"] == ["Application Log Content", "Network Traffic Content"]
    assert body["attack_version"] == "20.0"
    assert body["attack_collected_at"] == "2026-11-13T01:00:00Z"


def test_parent_lists_children_and_child_names_parent(loaded: str) -> None:
    parent = run_tool("get_attack_technique", {"technique_id": "T1059"})
    assert parent["subtechnique_count"] == 2
    assert [s["technique_id"] for s in parent["subtechniques"]] == ["T1059.001", "T1059.004"]
    child = run_tool("get_attack_technique", {"technique_id": "attack.T1059.004"})
    assert child["parent"] == {
        "technique_id": "T1059",
        "name": "Command and Scripting Interpreter",
    }
    assert "subtechniques" not in child


def test_unknown_technique_is_not_found(loaded: str) -> None:
    assert run_tool("get_attack_technique", {"technique_id": "T9999"})["status"] == "not_found"


def test_search_puts_name_matches_first_and_treats_wildcards_literally(loaded: str) -> None:
    body = run_tool("search_attack_techniques", {"query": "SHELL"})
    assert body["status"] == "ok"
    # 이름에 shell이 든 기법(PowerShell, Unix Shell)이 먼저, 설명에만 든 T1059가 뒤
    assert [r["technique_id"] for r in body["results"]] == ["T1059.001", "T1059.004", "T1059"]
    assert body["matched"] == 3
    one = run_tool("search_attack_techniques", {"query": "shell", "limit": 1})
    assert [r["technique_id"] for r in one["results"]] == ["T1059.001"]
    assert one["matched"] == 3 and one["returned"] == 1
    for wildcard in ("%%", "__", "a%"):
        assert run_tool("search_attack_techniques", {"query": wildcard})["matched"] == 0


def test_get_cve_found_and_not_in_kev(loaded: str) -> None:
    known = run_tool("get_cve", {"cve_id": "cve-2026-0002"})
    assert known["status"] == "found"
    assert known["known_ransomware_use"] == "Known"
    assert known["due_date"] == "2026-11-20"
    assert known["date_added"] == "2026-10-30"
    assert known["kev_catalog_version"] == "2026.11.03"
    assert known["kev_collected_at"] == "2026-11-13T01:00:00Z"
    other = run_tool("get_cve", {"cve_id": "CVE-2021-44228"})
    assert other["status"] == "not_in_kev"
    assert other["kev_collected_at"] == "2026-11-13T01:00:00Z"


def test_before_collection_everything_is_no_data(reader_url: str) -> None:
    for name, arguments in (
        ("get_attack_technique", {"technique_id": "T1190"}),
        ("search_attack_techniques", {"query": "public"}),
        ("get_cve", {"cve_id": "CVE-2026-0001"}),
    ):
        assert run_tool(name, arguments)["status"] == "no_data"


def test_other_configured_version_is_no_data(loaded: str) -> None:
    body = run_tool(
        "get_attack_technique", {"technique_id": "T1190"}, config(attack_version="19.0")
    )
    assert (body["status"], body["reason"]) == ("no_data", "attack_version_missing")


def test_rows_from_before_the_new_columns_are_not_served(migrated: str, loaded: str) -> None:
    with psycopg.connect(migrated, autocommit=True) as conn:
        conn.execute(
            "UPDATE attack_techniques SET description = NULL, collected_at = NULL"
            " WHERE technique_id = 'T1190'"
        )
    assert run_tool("get_attack_technique", {"technique_id": "T1190"})["status"] == "not_found"
    assert run_tool("get_attack_technique", {"technique_id": "T1059"})["status"] == "found"
    with psycopg.connect(migrated, autocommit=True) as conn:
        conn.execute("UPDATE attack_techniques SET description = NULL, collected_at = NULL")
    body = run_tool("get_attack_technique", {"technique_id": "T1059"})
    assert (body["status"], body["reason"]) == ("no_data", "attack_detail_not_collected")


def test_tools_work_without_python_network(loaded: str, monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("네트워크를 쓰면 안 된다")

    # 데이터베이스 접속은 libpq가 하므로 파이썬 소켓 연결·HTTP 호출만 막는다
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    assert run_tool("get_attack_technique", {"technique_id": "T1190"})["status"] == "found"
    assert run_tool("search_attack_techniques", {"query": "public"})["status"] == "ok"
    assert run_tool("get_cve", {"cve_id": "CVE-2026-0001"})["status"] == "found"
