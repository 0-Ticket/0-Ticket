"""화면용 API의 뼈대를 DB 없이 확인한다(#239): 라우트 목록, 설정, 오류 응답, 실행 명령."""

import logging
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.routing import APIRoute
from starlette.routing import Route
from starlette.testclient import TestClient

from soc.api import __main__ as api_main
from soc.api import db
from soc.api.app import create_app
from soc.api.config import ConfigError, load_settings
from soc.api.routes import hunts, threat_news
from soc.ids import new_id

# 닫힌 포트의 가짜 주소. 비밀번호와 호스트가 응답·로그에 나오지 않는지 본다
FAKE_URL = "postgresql://api_user:FAKE-PASSWORD-123@db.example.com:1/soc"


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    return TestClient(create_app(load_settings()))


def write_config(directory: Path, text: str) -> Path:
    (directory / "default.toml").write_text(text, encoding="utf-8")
    return directory


# 라우트


API_PATHS = ["/api/hunts", "/api/hunts/{hunt_id}", "/api/threat-news"]


def test_routes_are_get_only_under_api_and_openapi_is_the_only_other_route() -> None:
    app = create_app(load_settings())
    # FastAPI 0.162는 include_router한 라우터를 내부 객체(_IncludedRouter)로 감싸 app.routes에 둔다.
    # 그래서 앱 바로 아래의 Starlette 라우트와, 포함한 라우터 각각의 라우트를 따로 본다
    direct = [r for r in app.routes if isinstance(r, Route)]
    assert [(r.path, sorted(r.methods or ())) for r in direct] == [
        ("/openapi.json", ["GET", "HEAD"])
    ]
    included = [*hunts.router.routes, *threat_news.router.routes]
    assert all(isinstance(r, APIRoute) for r in included)
    assert sorted("/api" + r.path for r in included) == API_PATHS
    for route in included:
        assert route.methods == {"GET"}
        assert route.include_in_schema
    # 앱에 실제로 붙은 모양은 OpenAPI 문서로 본다
    paths = app.openapi()["paths"]
    assert sorted(paths) == API_PATHS
    for operations in paths.values():
        assert list(operations) == ["get"]


def test_docs_pages_are_off(client: TestClient) -> None:
    for path in ("/docs", "/redoc"):
        response = client.get(path)
        assert response.status_code == 404
        assert response.json() == {"error": "not_found"}


# 설정


def test_default_settings() -> None:
    settings = load_settings()
    assert settings.host == "127.0.0.1"
    assert settings.port == 8000
    assert settings.statement_timeout_ms == 5000
    assert settings.connect_timeout_seconds == 5
    assert settings.attack_version == "20.0"


def test_local_config_overrides_default(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        '[api]\nhost = "127.0.0.1"\nport = 8000\nstatement_timeout_ms = 5000\n'
        'connect_timeout_seconds = 5\n[l3.intel.attack]\nversion = "20.0"\n',
    )
    (tmp_path / "local.toml").write_text(
        '[api]\nport = 9000\n[l3.intel.attack]\nversion = "19.0"\n', encoding="utf-8"
    )
    settings = load_settings(tmp_path)
    assert settings.port == 9000
    assert settings.attack_version == "19.0"


GOOD_API = {
    "host": '"127.0.0.1"',
    "port": "8000",
    "statement_timeout_ms": "5000",
    "connect_timeout_seconds": "5",
}


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("host", '""'),
        ("port", "0"),
        ("port", "70000"),
        ("port", '"8000"'),
        ("statement_timeout_ms", "0"),
        ("connect_timeout_seconds", "true"),
        ("connect_timeout_seconds", None),
    ],
)
def test_bad_settings_raise_config_error(tmp_path: Path, key: str, value: str | None) -> None:
    api = {**GOOD_API, key: value}
    lines = "".join(f"{k} = {v}\n" for k, v in api.items() if v is not None)
    write_config(tmp_path, f'[api]\n{lines}[l3.intel.attack]\nversion = "20.0"\n')
    with pytest.raises(ConfigError):
        load_settings(tmp_path)


def test_missing_attack_version_is_config_error(tmp_path: Path) -> None:
    write_config(
        tmp_path,
        '[api]\nhost = "127.0.0.1"\nport = 8000\nstatement_timeout_ms = 5000\n'
        "connect_timeout_seconds = 5\n",
    )
    with pytest.raises(ConfigError):
        load_settings(tmp_path)


# 오류 응답


def test_missing_database_url_is_503(client: TestClient) -> None:
    for path in ("/api/hunts", f"/api/hunts/{new_id('hnt')}", "/api/threat-news"):
        response = client.get(path)
        assert response.status_code == 503
        assert response.json() == {"error": "db_unavailable"}


def test_unreachable_db_is_503_without_address(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)
    client = TestClient(create_app(load_settings()))
    with caplog.at_level(logging.DEBUG):
        response = client.get("/api/hunts")
    assert response.status_code == 503
    assert response.json() == {"error": "db_unavailable"}
    for secret in ("FAKE-PASSWORD-123", "db.example.com", "api_user"):
        assert secret not in response.text
        assert secret not in caplog.text


@pytest.mark.parametrize(
    ("path", "params", "fields"),
    [
        ("/api/hunts", {"limit": "zz<script>"}, ["limit"]),
        ("/api/hunts", {"limit": "0"}, ["limit"]),
        ("/api/hunts", {"limit": "201"}, ["limit"]),
        ("/api/hunts", {"status": "<b>open</b>"}, ["status"]),
        ("/api/hunts", {"hunt_run_id": "hrn_x' OR 1=1"}, ["hunt_run_id"]),
        ("/api/hunts", {"cursor": "tkt_0"}, ["cursor"]),
        ("/api/hunts", {"limit": "xx1", "status": "yy2"}, ["limit", "status"]),
        ("/api/threat-news", {"source": ""}, ["source"]),
        ("/api/threat-news", {"since": "-1"}, ["since"]),
        ("/api/threat-news", {"until": "253402214400000"}, ["until"]),
        ("/api/threat-news", {"since": "10", "until": "9"}, ["since", "until"]),
        ("/api/threat-news", {"cursor": "abc"}, ["cursor"]),
        ("/api/threat-news", {"cursor": "1_99999999999999999999"}, ["cursor"]),
        ("/api/threat-news", {"cursor": "253402214400000_1"}, ["cursor"]),
    ],
)
def test_bad_query_is_422_with_field_names_only(
    client: TestClient, path: str, params: dict[str, str], fields: list[str]
) -> None:
    response = client.get(path, params=params)
    assert response.status_code == 422
    assert response.json() == {"error": "invalid_query", "fields": fields}
    for value in params.values():
        if value:
            assert value not in response.text


@pytest.mark.parametrize("hunt_id", ["abc", "hrn_0", "<script>", "tkt_" + new_id("hnt")[4:]])
def test_malformed_hunt_id_is_404_without_input(client: TestClient, hunt_id: str) -> None:
    response = client.get(f"/api/hunts/{hunt_id}")
    assert response.status_code == 404
    assert response.json() == {"error": "not_found"}
    assert hunt_id not in response.text


def test_unknown_path_is_404(client: TestClient) -> None:
    response = client.get("/api/unknown<script>")
    assert response.status_code == 404
    assert response.json() == {"error": "not_found"}


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_non_get_is_405(client: TestClient, method: str) -> None:
    response = client.request(method, "/api/hunts")
    assert response.status_code == 405
    assert response.json() == {"error": "method_not_allowed"}


def test_unexpected_error_is_500_without_message(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    @contextmanager
    def fake_connect(settings: object):
        yield object()

    def boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("SECRET-DETAIL-xyz")

    monkeypatch.setattr(db, "connect", fake_connect)
    monkeypatch.setattr(hunts, "read_hunt_page", boom)
    # 기본 TestClient는 앱 밖으로 올라온 예외를 다시 올린다.
    # 500을 받으면 예외가 앱 안에서 끝난 것이다
    client = TestClient(create_app(load_settings()))
    with caplog.at_level(logging.DEBUG):
        response = client.get("/api/hunts")
    assert response.status_code == 500
    assert response.json() == {"error": "internal"}
    assert "SECRET-DETAIL-xyz" not in response.text
    assert "SECRET-DETAIL-xyz" not in caplog.text
    assert "RuntimeError" in caplog.text


# 실행 명령


def test_main_without_database_url_exits_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    called: list[object] = []
    monkeypatch.setattr(api_main.uvicorn, "run", lambda *a, **k: called.append(a))
    assert api_main.main() == 2
    assert called == []
    assert "DATABASE_URL" in capsys.readouterr().out


def test_main_runs_uvicorn_on_configured_host_and_port(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)
    called: list[dict[str, object]] = []
    monkeypatch.setattr(api_main.uvicorn, "run", lambda app, **kwargs: called.append(kwargs))
    assert api_main.main() == 0
    assert called == [{"host": "127.0.0.1", "port": 8000}]
    out = capsys.readouterr().out
    assert "FAKE-PASSWORD-123" not in out
    assert "db.example.com" not in out


def test_main_with_bad_config_exits_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("DATABASE_URL", FAKE_URL)

    def bad(*args: object, **kwargs: object) -> object:
        raise ConfigError("[api] port는 1~65535 정수여야 한다")

    monkeypatch.setattr(api_main, "load_settings", bad)
    assert api_main.main() == 2
    assert "port" in capsys.readouterr().out
