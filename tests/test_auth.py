"""인증·권한의 DB 없는 부분(#284): 권한 목록, 비밀번호 해시, 설정, 기본 거부, 권한 표, CSRF."""

import uuid
from pathlib import Path

import pytest
from auth_support import ORIGIN, admin_client, make_client, make_user
from starlette.testclient import TestClient

from soc.api import auth as api_auth
from soc.api.app import create_app
from soc.api.config import ConfigError, load_settings
from soc.auth import passwords
from soc.auth.permissions import ANALYST_DEFAULT, PERMISSIONS, UNUSED

UID = str(uuid.UUID(int=7))

# 권한


def test_permission_catalog_has_16_names_and_9_analyst_defaults() -> None:
    assert len(PERMISSIONS) == 16
    assert len(set(PERMISSIONS)) == 16
    assert all(name.count(".") == 1 for name in PERMISSIONS)
    assert set(ANALYST_DEFAULT) <= set(PERMISSIONS)
    assert len(ANALYST_DEFAULT) == 9
    assert all(name.endswith(".read") and name != "user.read" for name in ANALYST_DEFAULT)
    assert UNUSED == {"incident.approve", "incident.reject", "incident.close"}


def test_every_permission_but_the_approval_ones_guards_a_route() -> None:
    create_app(load_settings())
    assert set(PERMISSIONS) - api_auth.USED_PERMISSIONS == UNUSED


# 비밀번호


def test_password_hash_verifies_and_is_argon2id() -> None:
    hashed = passwords.hash_password("test-only-password-0001")
    assert hashed.startswith("$argon2id$")
    assert "test-only" not in hashed
    assert passwords.verify_password(hashed, "test-only-password-0001")
    assert not passwords.verify_password(hashed, "test-only-password-0002")
    assert not passwords.verify_password("not-a-hash", "x")


def test_unknown_user_check_still_runs_a_hash_verification() -> None:
    assert passwords.verify_password(passwords.DUMMY_HASH, "anything") is False


# 설정


def test_default_auth_settings() -> None:
    auth = load_settings().auth
    assert auth.idle_timeout_seconds == 3600
    assert auth.absolute_timeout_seconds == 43200
    assert auth.cookie_name == "soc_session"
    assert auth.cookie_secure is False
    assert auth.allowed_origins == ("http://127.0.0.1:5173", "http://localhost:5173")


API = (
    '[api]\nhost = "127.0.0.1"\nport = 8000\nstatement_timeout_ms = 5000\n'
    'connect_timeout_seconds = 5\n[l3.intel.attack]\nversion = "20.0"\n'
)
GOOD_AUTH = {
    "idle_timeout_seconds": "3600",
    "absolute_timeout_seconds": "43200",
    "cookie_name": '"soc_session"',
    "cookie_secure": "false",
    "allowed_origins": '["http://127.0.0.1:5173"]',
}


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("idle_timeout_seconds", "0"),
        ("idle_timeout_seconds", "true"),
        ("absolute_timeout_seconds", '"1"'),
        ("cookie_name", '""'),
        ("cookie_name", '"bad name;"'),
        ("cookie_secure", '"yes"'),
        ("allowed_origins", "[]"),
        ("allowed_origins", '["http://example.com/path"]'),
        ("allowed_origins", '["*"]'),
        ("allowed_origins", '"http://example.com"'),
        ("cookie_name", None),
    ],
)
def test_bad_auth_settings_raise_config_error(tmp_path: Path, key: str, value: str | None) -> None:
    auth = {**GOOD_AUTH, key: value}
    lines = "".join(f"{k} = {v}\n" for k, v in auth.items() if v is not None)
    (tmp_path / "default.toml").write_text(f"{API}[auth]\n{lines}", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(tmp_path)


def test_missing_auth_section_is_config_error(tmp_path: Path) -> None:
    (tmp_path / "default.toml").write_text(API, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(tmp_path)


# 기본 거부

PUBLIC = {("POST", "/api/auth/login"), ("POST", "/api/auth/signup")}


def all_operations() -> list[tuple[str, str]]:
    app = create_app(load_settings())
    found = [
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    ]
    return [*found, ("GET", "/api/openapi.json")]


def fill(path: str) -> str:
    return (
        path.replace("{hunt_id}", "x")
        .replace("{record_id}", "x")
        .replace("{ticket_id}", "x")
        .replace("{incident_id}", "x")
        .replace("{case_id}", "x")
        .replace("{user_id}", UID)
    )


def test_every_route_but_login_and_signup_needs_a_session() -> None:
    client = make_client()
    operations = all_operations()
    assert PUBLIC <= set(operations)
    assert len(operations) >= 30
    for method, path in operations:
        response = client.request(method, fill(path))
        if (method, path) in PUBLIC:
            assert response.status_code != 401, (method, path)
        else:
            assert response.status_code == 401, (method, path, response.status_code)
            assert response.json() == {"error": "unauthenticated"}


def test_openapi_json_moved_under_api_and_needs_login() -> None:
    client = make_client()
    assert client.get("/openapi.json").status_code == 404
    assert client.get("/api/openapi.json").status_code == 401
    logged_in = make_client(make_user("analyst", frozenset()))
    response = logged_in.get("/api/openapi.json")
    assert response.status_code == 200
    assert "/api/auth/login" in response.json()["paths"]


# 권한 표: (메서드, 경로, 필요한 권한, 요청 본문)
BODY_ROLE = {"role": "analyst"}
PERMISSION_TABLE = [
    ("GET", "/api/dashboard", "dashboard.read", None),
    ("GET", "/api/alerts", "alert.read", None),
    ("GET", "/api/alerts/x", "alert.read", None),
    ("GET", "/api/events", "event.read", None),
    ("GET", "/api/events/x", "event.read", None),
    ("GET", "/api/tickets", "ticket.read", None),
    ("GET", "/api/tickets/x", "ticket.read", None),
    ("GET", "/api/incidents", "incident.read", None),
    ("GET", "/api/incidents/x", "incident.read", None),
    ("GET", "/api/cases", "case.read", None),
    ("GET", "/api/cases/x", "case.read", None),
    ("GET", "/api/hunts", "hunt.read", None),
    ("GET", "/api/hunts/x", "hunt.read", None),
    ("GET", "/api/threat-news", "news.read", None),
    ("GET", "/api/ticketing-policy", "policy.read", None),
    (
        "PUT",
        "/api/ticketing-policy",
        "policy.update",
        {"mode": "auto", "scenario_rule_ids": []},
    ),
    ("GET", "/api/users", "user.read", None),
    ("GET", "/api/permissions", "user.read", None),
    ("POST", f"/api/users/{UID}/approve", "user.approve", BODY_ROLE),
    ("POST", f"/api/users/{UID}/reject", "user.approve", None),
    ("POST", f"/api/users/{UID}/disable", "user.approve", None),
    (
        "POST",
        f"/api/users/{UID}/reset-password",
        "user.approve",
        {"temporary_password": "test-only-password-0003"},
    ),
    ("PUT", f"/api/users/{UID}/permissions", "user.permission", {"permissions": []}),
]


def test_permission_table_covers_every_protected_route() -> None:
    covered = {(m, p) for m, p, _, _ in PERMISSION_TABLE}
    login_only = {
        ("PATCH", f"/api/users/{UID}"),  # 역할 변경은 권한이 아니라 admin 역할이 필요하다
        ("GET", "/api/auth/me"),
        ("POST", "/api/auth/logout"),
        ("POST", "/api/auth/password"),
        ("GET", "/api/openapi.json"),
    }
    expected = set()
    for method, path in all_operations():
        if (method, fill(path)) not in PUBLIC | login_only:
            expected.add((method, fill(path)))
    assert covered == expected


@pytest.mark.parametrize(("method", "path", "permission", "body"), PERMISSION_TABLE)
def test_route_needs_exactly_its_permission(
    monkeypatch: pytest.MonkeyPatch, method: str, path: str, permission: str, body: object
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    without = make_client(make_user("analyst", frozenset(PERMISSIONS) - {permission}))
    denied = without.request(method, path, json=body)
    assert denied.status_code == 403
    assert denied.json() == {"error": "permission_denied"}
    with_only = make_client(make_user("analyst", frozenset({permission})))
    allowed = with_only.request(method, path, json=body)
    assert allowed.status_code not in (401, 403), allowed.text
    admin = admin_client()
    assert admin.request(method, path, json=body).status_code not in (401, 403)


def test_role_change_is_admin_only_whatever_permissions_an_analyst_holds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    path = f"/api/users/{UID}"
    analyst = make_client(make_user("analyst", frozenset(PERMISSIONS)))
    denied = analyst.patch(path, json=BODY_ROLE)
    assert (denied.status_code, denied.json()) == (403, {"error": "forbidden"})
    assert admin_client().patch(path, json=BODY_ROLE).status_code not in (401, 403)


def test_password_change_required_blocks_everything_but_three_routes() -> None:
    client = make_client(make_user("admin", must_change_password=True))
    for method, path, _, body in PERMISSION_TABLE:
        response = client.request(method, path, json=body)
        assert response.status_code == 403, path
        assert response.json() == {"error": "password_change_required"}
    assert client.get("/api/openapi.json").status_code == 403
    assert client.patch(f"/api/users/{UID}", json=BODY_ROLE).status_code == 403
    me = client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.json()["must_change_password"] is True


def test_me_returns_user_and_sorted_permissions() -> None:
    client = make_client(make_user("analyst", frozenset({"hunt.read", "alert.read"})))
    body = client.get("/api/auth/me").json()
    assert body["role"] == "analyst"
    assert body["permissions"] == ["alert.read", "hunt.read"]
    assert set(body) == {
        "id",
        "username",
        "display_name",
        "role",
        "must_change_password",
        "permissions",
    }


def test_require_role_admin_is_admin_only() -> None:
    from fastapi import Depends, FastAPI

    app = FastAPI()
    app.dependency_overrides[api_auth.session_user] = lambda: make_user("analyst", frozenset())

    admin_only = Depends(api_auth.require_role("admin"))

    @app.get("/x", dependencies=[admin_only])
    def route() -> dict[str, str]:
        return {"ok": "yes"}

    from soc.api import errors

    errors.install(app)
    assert TestClient(app).get("/x").status_code == 403
    app.dependency_overrides[api_auth.session_user] = lambda: make_user("admin")
    assert TestClient(app).get("/x").status_code == 200


# CSRF


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_changing_requests_need_an_allowed_origin(method: str) -> None:
    client = TestClient(create_app(load_settings()))
    missing = client.request(method, "/api/auth/login")
    assert missing.status_code == 403
    assert missing.json() == {"error": "origin_not_allowed"}
    wrong = client.request(method, "/api/auth/login", headers={"origin": "http://evil.example"})
    assert wrong.status_code == 403
    assert wrong.json() == {"error": "origin_not_allowed"}
    ok = client.request(method, "/api/auth/login", headers={"origin": ORIGIN})
    assert ok.json() != {"error": "origin_not_allowed"}


def test_reads_do_not_need_an_origin() -> None:
    client = TestClient(create_app(load_settings()))
    assert client.get("/api/auth/me").status_code == 401


@pytest.mark.parametrize(
    ("params", "fields"),
    [
        ({"cursor": "bad"}, ["cursor"]),
        ({"cursor": "123_not-a-uuid"}, ["cursor"]),
        ({"cursor": "1_AAAAAAAA-0000-0000-0000-000000000000"}, ["cursor"]),
        ({"limit": "0"}, ["limit"]),
        ({"limit": "201"}, ["limit"]),
        ({"status": "deleted"}, ["status"]),
    ],
)
def test_bad_users_query_is_422_with_field_names_only(
    monkeypatch: pytest.MonkeyPatch, params: dict[str, str], fields: list[str]
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    response = admin_client().get("/api/users", params=params)
    assert response.status_code == 422
    assert response.json() == {"error": "invalid_query", "fields": fields}


# 요청 본문 검사


@pytest.mark.parametrize(
    ("path", "body", "fields"),
    [
        (
            "/api/auth/signup",
            {"username": "ab", "display_name": "x", "password": "x" * 12},
            ["username"],
        ),
        (
            "/api/auth/signup",
            {"username": "alice", "display_name": "", "password": "x" * 12},
            ["display_name"],
        ),
        (
            "/api/auth/signup",
            {"username": "alice", "display_name": "A", "password": "short"},
            ["password"],
        ),
        (
            "/api/auth/signup",
            {"username": "Bad Name!", "display_name": "A", "password": "x" * 12},
            ["username"],
        ),
        ("/api/auth/login", {"username": "alice"}, ["password"]),
    ],
)
def test_bad_body_is_422_with_field_names_only(
    monkeypatch: pytest.MonkeyPatch, path: str, body: dict[str, str], fields: list[str]
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    response = make_client().post(path, json=body)
    assert response.status_code == 422
    assert response.json() == {"error": "invalid_body", "fields": fields}
    for value in body.values():
        if len(value) > 3:
            assert value not in response.text
