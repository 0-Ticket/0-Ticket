"""db 마커 테스트가 쓰는 임시 DB.

DATABASE_URL로 접속해 soc_test_<랜덤> DB를 만들고, 테스트가 끝나면 지운다.
개발 DB의 테이블은 건드리지 않는다. DATABASE_URL이 없으면 건너뛰지 않고 실패한다.
"""

import os
import secrets
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import psycopg
import pytest
from psycopg import sql
from psycopg.conninfo import make_conninfo

REPO_CONFIG = Path(__file__).resolve().parents[1] / "config"


@pytest.fixture
def default_config_dir(tmp_path: Path) -> Path:
    """저장소 config/default.toml만 복사한 폴더(#224).

    기본값을 검사하는 테스트가 config/local.toml(커밋 안 함, 사람마다 다름)의 영향을 받지 않게 한다.
    설정 로더에 load_config(default_config_dir)로 넘긴다.
    """
    directory = tmp_path / "default-config"
    directory.mkdir()
    shutil.copyfile(REPO_CONFIG / "default.toml", directory / "default.toml")
    return directory


class HiddenUrl(str):
    """테스트가 실패해도 pytest 출력에 주소(비밀번호 포함)가 찍히지 않게 repr을 가린다."""

    def __repr__(self) -> str:
        return "'<DB 주소>'"


@pytest.fixture
def database_url() -> HiddenUrl:
    url = os.environ.get("DATABASE_URL")
    if not url:
        pytest.fail("db 테스트에는 환경변수 DATABASE_URL이 필요하다", pytrace=False)
    return HiddenUrl(url)


@contextmanager
def created_database(database_url: HiddenUrl) -> Iterator[HiddenUrl]:
    name = f"soc_test_{secrets.token_hex(6)}"
    with psycopg.connect(database_url, autocommit=True) as admin:
        admin.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    try:
        yield HiddenUrl(make_conninfo(database_url, dbname=name))
    finally:
        with psycopg.connect(database_url, autocommit=True) as admin:
            admin.execute(
                sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(sql.Identifier(name))
            )


@pytest.fixture
def temp_database(database_url: HiddenUrl) -> Iterator[HiddenUrl]:
    with created_database(database_url) as url:
        yield url


@pytest.fixture
def other_temp_database(database_url: HiddenUrl) -> Iterator[HiddenUrl]:
    """같은 서버의 두 번째 임시 DB. DB끼리 서로 영향을 주지 않는지 볼 때 쓴다."""
    with created_database(database_url) as url:
        yield url


@pytest.fixture(autouse=True)
def _clear_tool_services():
    """실행기가 등록하는 도구 공유 객체(#313)가 테스트 사이에 새지 않게 한다."""
    from soc.tools import services

    services.clear()
    yield
    services.clear()
