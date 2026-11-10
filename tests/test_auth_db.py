"""인증·세션·승인·권한을 실제 PostgreSQL과 실제 로그인으로 확인한다(#284, db 마커).

샘플: tests/fixtures/auth/accounts.json(가짜 계정, 테스트 전용 비밀번호).
"""

import dataclasses
import hashlib
import json
import logging
import re
import threading
from pathlib import Path

import psycopg
import pytest
from auth_support import ORIGIN, make_client
from starlette.testclient import TestClient

from soc.api import __main__ as api_main
from soc.api import db as api_db
from soc.api.config import load_settings
from soc.auth import store
from soc.auth.permissions import ANALYST_DEFAULT, PERMISSIONS
from soc.db.migrate import migrate

pytestmark = pytest.mark.db

ACC = json.loads((Path(__file__).parent / "fixtures/auth/accounts.json").read_text("utf-8"))
PW, NEW_PW = ACC["password"], ACC["new_password"]
NAMES = [a["username"] for a in ACC["accounts"]]
CONSOLE = re.compile(r"임시 비밀번호: (\S+)")


@pytest.fixture
def url(temp_database, monkeypatch):
    migrate(temp_database)
    monkeypatch.setenv("DATABASE_URL", temp_database)
    return temp_database


def first_admin() -> str:
    with api_db.connect_write(load_settings()) as conn:
        password = store.ensure_first_admin(conn)
    assert password
    return password


def login(client: TestClient, username: str, password: str = PW):
    return client.post("/api/auth/login", json={"username": username, "password": password})


@pytest.fixture
def admin(url) -> TestClient:
    """임시 비밀번호를 바꾼 최초 관리자로 로그인한 클라이언트."""
    temp = first_admin()
    client = make_client()
    assert login(client, "admin", temp).status_code == 200
    changed = client.post("/api/auth/password", json={"current_password": temp, "new_password": PW})
    assert changed.status_code == 200, changed.text
    return client


def user_id(admin: TestClient, username: str) -> str:
    items = admin.get("/api/users").json()["items"]
    return next(u["id"] for u in items if u["username"] == username)


def signup(username: str, password: str = PW):
    return make_client().post(
        "/api/auth/signup",
        json={"username": username, "display_name": f"{username} Example", "password": password},
    )


def make_user(admin: TestClient, username: str, role: str = "analyst") -> str:
    assert signup(username).status_code == 201
    uid = user_id(admin, username)
    approved = admin.post(f"/api/users/{uid}/approve", json={"role": role})
    assert approved.status_code == 200, approved.text
    return uid


def session_client(username: str, password: str = PW) -> TestClient:
    client = make_client()
    response = login(client, username, password)
    assert response.status_code == 200, response.text
    return client


def perms(admin: TestClient, uid: str) -> list[str]:
    users = admin.get("/api/users").json()["items"]
    return next(u["permissions"] for u in users if u["id"] == uid)


def sql(url, query: str, params=()):
    with psycopg.connect(url, autocommit=True) as conn:
        cursor = conn.execute(query, params)
        return cursor.fetchall() if cursor.description else []


# 최초 관리자


def test_first_admin_is_created_once_and_password_is_printed_once(
    url, monkeypatch, capsys, caplog
) -> None:
    monkeypatch.setattr(api_main.uvicorn, "run", lambda *a, **k: None)
    with caplog.at_level(logging.DEBUG):
        assert api_main.main() == 0
        first = capsys.readouterr().out
        assert api_main.main() == 0
        second = capsys.readouterr().out
    temp = CONSOLE.search(first).group(1)
    assert len(temp) >= 20
    assert first.count(temp) == 1
    assert temp not in second and "임시 비밀번호" not in second
    assert temp not in caplog.text
    rows = sql(url, "SELECT username, role, status, must_change_password, password_hash FROM users")
    assert len(rows) == 1
    assert rows[0][:4] == ("admin", "admin", "active", True)
    assert temp not in rows[0][4]


def test_concurrent_starts_make_exactly_one_admin(url) -> None:
    results: list[str | None] = []

    def start() -> None:
        with api_db.connect_write(load_settings()) as conn:
            results.append(store.ensure_first_admin(conn))

    threads = [threading.Thread(target=start) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len([r for r in results if r]) == 1
    assert sql(url, "SELECT count(*) FROM users") == [(1,)]


def test_main_without_migration_exits_2(temp_database, monkeypatch, capsys) -> None:
    monkeypatch.setenv("DATABASE_URL", temp_database)
    monkeypatch.setattr(api_main.uvicorn, "run", lambda *a, **k: None)
    assert api_main.main() == 2
    assert "soc.db.migrate" in capsys.readouterr().out


def test_temporary_password_blocks_everything_until_changed(url) -> None:
    temp = first_admin()
    client = make_client()
    assert login(client, "admin", temp).status_code == 200
    blocked = client.get("/api/dashboard")
    assert (blocked.status_code, blocked.json()) == (403, {"error": "password_change_required"})
    assert client.get("/api/auth/me").json()["must_change_password"] is True
    short = client.post(
        "/api/auth/password", json={"current_password": temp, "new_password": "short"}
    )
    assert short.status_code == 422
    wrong = client.post("/api/auth/password", json={"current_password": PW, "new_password": NEW_PW})
    assert wrong.status_code == 401
    ok = client.post("/api/auth/password", json={"current_password": temp, "new_password": PW})
    assert ok.status_code == 200
    assert ok.json()["must_change_password"] is False
    assert client.get("/api/dashboard").status_code == 200
    assert login(make_client(), "admin", temp).status_code == 401
    assert login(make_client(), "admin", PW).status_code == 200


# 가입과 승인


def test_signup_pending_login_approve_flow(admin) -> None:
    assert signup("alice").status_code == 201
    uid = user_id(admin, "alice")
    wrong = login(make_client(), "alice", NEW_PW)
    pending = login(make_client(), "alice")
    assert (wrong.status_code, wrong.json()) == (401, {"error": "invalid_credentials"})
    assert (pending.status_code, pending.json()) == (403, {"error": "account_pending"})
    approved = admin.post(f"/api/users/{uid}/approve", json={"role": "analyst"})
    assert approved.status_code == 200
    assert approved.json()["status"] == "active"
    assert approved.json()["permissions"] == sorted(ANALYST_DEFAULT)
    alice = session_client("alice")
    assert alice.get("/api/dashboard").status_code == 200
    assert alice.get("/api/hunts").status_code == 200
    assert alice.get("/api/users").status_code == 403
    me = alice.get("/api/auth/me").json()
    assert (me["username"], me["role"], me["display_name"]) == ("alice", "analyst", "alice Example")


def test_login_failure_is_the_same_for_unknown_user_and_wrong_password(admin) -> None:
    unknown = login(make_client(), "nobody")
    wrong = login(make_client(), "admin", NEW_PW)
    assert unknown.status_code == wrong.status_code == 401
    assert unknown.json() == wrong.json() == {"error": "invalid_credentials"}
    assert unknown.headers.get("set-cookie") is None


def test_reject_disable_and_duplicate_signup(admin) -> None:
    assert signup("bob").status_code == 201
    bob = user_id(admin, "bob")
    assert admin.post(f"/api/users/{bob}/reject").json()["status"] == "rejected"
    rejected = login(make_client(), "bob")
    assert (rejected.status_code, rejected.json()) == (403, {"error": "account_rejected"})
    again = signup("bob")
    assert (again.status_code, again.json()) == (409, {"error": "username_taken"})
    assert signup("BOB").status_code == 409
    carol = make_user(admin, "carol")
    session = session_client("carol")
    assert admin.post(f"/api/users/{carol}/disable").json()["status"] == "disabled"
    assert session.get("/api/auth/me").status_code == 401
    disabled = login(make_client(), "carol")
    assert (disabled.status_code, disabled.json()) == (403, {"error": "account_disabled"})
    assert admin.post(f"/api/users/{carol}/approve", json={"role": "analyst"}).status_code == 409


def test_users_list_pages_in_creation_order_without_gaps(admin) -> None:
    for name in ("alice", "bob", "carol", "dave.ops"):
        assert signup(name).status_code == 201

    def pages(**params):
        found, cursor = [], None
        while True:
            query = {"limit": 2, **params, **({"cursor": cursor} if cursor else {})}
            body = admin.get("/api/users", params=query).json()
            assert len(body["items"]) <= 2
            found += [u["username"] for u in body["items"]]
            cursor = body["next_cursor"]
            if cursor is None:
                return found

    assert pages() == ["admin", "alice", "bob", "carol", "dave.ops"]
    assert pages(status="pending") == ["alice", "bob", "carol", "dave.ops"]
    last = admin.get("/api/users", params={"limit": 5}).json()
    assert last["next_cursor"] is None
    assert len(last["items"]) == 5


def test_users_list_and_permission_catalog(admin) -> None:
    make_user(admin, "alice")
    items = admin.get("/api/users").json()["items"]
    assert [u["username"] for u in items] == ["admin", "alice"]
    assert admin.get("/api/users", params={"status": "pending"}).json()["items"] == []
    assert set(items[0]) >= {"id", "username", "display_name", "role", "status", "permissions"}
    assert "password_hash" not in json.dumps(items)
    catalog = admin.get("/api/permissions").json()["permissions"]
    assert [p["name"] for p in catalog] == sorted(PERMISSIONS)
    assert {p["name"] for p in catalog if p["analyst_default"]} == set(ANALYST_DEFAULT)
    assert admin.get("/api/users/not-a-uuid/x").status_code == 404
    assert admin.post("/api/users/not-a-uuid/disable").status_code == 404


# 역할 변경과 마지막 admin


def test_role_change_expires_sessions_and_resets_permissions(url, admin) -> None:
    alice = make_user(admin, "alice")
    session = session_client("alice")
    promoted = admin.patch(f"/api/users/{alice}", json={"role": "admin"})
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "admin"
    assert session.get("/api/auth/me").status_code == 401
    assert sql(url, "SELECT count(*) FROM user_permissions WHERE user_id = %s", (alice,)) == [(0,)]
    assert session_client("alice").get("/api/users").status_code == 200
    admin.patch(f"/api/users/{alice}", json={"role": "analyst"})
    assert perms(admin, alice) == sorted(ANALYST_DEFAULT)
    assert session_client("alice").get("/api/users").status_code == 403


def test_last_admin_cannot_be_demoted_or_disabled(admin) -> None:
    me = user_id(admin, "admin")
    assert admin.patch(f"/api/users/{me}", json={"role": "analyst"}).json() == {
        "error": "last_admin"
    }
    assert admin.post(f"/api/users/{me}/disable").json() == {"error": "last_admin"}
    assert admin.get("/api/auth/me").status_code == 200


def test_two_admins_cannot_remove_each_other_at_once(url, admin) -> None:
    second = make_user(admin, "alice", "admin")
    first = user_id(admin, "admin")
    other_client = session_client("alice")
    codes: list[int] = []

    def demote(client: TestClient, target: str) -> None:
        codes.append(client.patch(f"/api/users/{target}", json={"role": "analyst"}).status_code)

    threads = [
        threading.Thread(target=demote, args=(admin, second)),
        threading.Thread(target=demote, args=(other_client, first)),
    ]
    [t.start() for t in threads]
    [t.join() for t in threads]
    # 하나만 성공한다. 진 쪽은 세션이 이미 끝났거나(401) 마지막 admin 보호(409)에 걸린다
    assert sorted(codes) in ([200, 401], [200, 409])
    assert sql(url, "SELECT count(*) FROM users WHERE role = 'admin' AND status = 'active'") == [
        (1,)
    ]


# 세션


def test_idle_and_absolute_expiry_and_sliding(url, admin) -> None:
    make_user(admin, "alice")
    client = session_client("alice")
    sql(url, "UPDATE user_sessions SET last_seen_at = now() - interval '59 minutes'")
    assert client.get("/api/auth/me").status_code == 200
    (seen,) = sql(
        url,
        "SELECT last_seen_at > now() - interval '1 minute' FROM user_sessions "
        "WHERE user_id = (SELECT id FROM users WHERE username = 'alice')",
    )[0]
    assert seen is True
    sql(url, "UPDATE user_sessions SET last_seen_at = now() - interval '61 minutes'")
    assert client.get("/api/auth/me").status_code == 401
    client = session_client("alice")
    sql(url, "UPDATE user_sessions SET expires_at = now() - interval '1 second'")
    assert client.get("/api/auth/me").status_code == 401


def test_password_change_expires_other_sessions_and_rotates_current(url, admin) -> None:
    make_user(admin, "alice")
    first, second = session_client("alice"), session_client("alice")
    before = second.cookies.get("soc_session")
    changed = second.post(
        "/api/auth/password", json={"current_password": PW, "new_password": NEW_PW}
    )
    assert changed.status_code == 200
    assert first.get("/api/auth/me").status_code == 401
    assert second.get("/api/auth/me").status_code == 200
    assert second.cookies.get("soc_session") != before
    assert login(make_client(), "alice", PW).status_code == 401
    assert login(make_client(), "alice", NEW_PW).status_code == 200


def test_logout_deletes_the_session(url, admin) -> None:
    make_user(admin, "alice")
    client = session_client("alice")
    token = client.cookies.get("soc_session")
    assert client.post("/api/auth/logout").status_code == 204
    assert sql(
        url,
        "SELECT count(*) FROM user_sessions WHERE token_hash = %s",
        (hashlib.sha256(token.encode()).hexdigest(),),
    ) == [(0,)]
    assert client.get("/api/auth/me").status_code == 401


def test_cookie_attributes_and_token_is_stored_hashed(url, admin) -> None:
    make_user(admin, "alice")
    client = make_client()
    response = login(client, "alice")
    cookie = response.headers["set-cookie"]
    assert cookie.startswith("soc_session=")
    for part in ("HttpOnly", "SameSite=lax", "Path=/", "Max-Age=43200"):
        assert part in cookie
    assert "Secure" not in cookie
    token = client.cookies.get("soc_session")
    stored = sql(
        url,
        "SELECT token_hash FROM user_sessions WHERE token_hash = %s",
        (hashlib.sha256(token.encode()).hexdigest(),),
    )
    assert len(stored) == 1
    assert token not in json.dumps(sql(url, "SELECT * FROM user_sessions"), default=str)
    settings = load_settings()
    secure = dataclasses.replace(
        settings, auth=dataclasses.replace(settings.auth, cookie_secure=True)
    )
    response = login(make_client(settings=secure), "alice")
    assert "Secure" in response.headers["set-cookie"]


def test_origin_is_checked_on_the_real_login(url, admin) -> None:
    bare = TestClient(make_client().app)
    response = bare.post("/api/auth/login", json={"username": "admin", "password": PW})
    assert (response.status_code, response.json()) == (403, {"error": "origin_not_allowed"})
    wrong = bare.post(
        "/api/auth/login",
        json={"username": "admin", "password": PW},
        headers={"origin": "http://evil.example"},
    )
    assert wrong.status_code == 403
    ok = bare.post(
        "/api/auth/login", json={"username": "admin", "password": PW}, headers={"origin": ORIGIN}
    )
    assert ok.status_code == 200


# 관리자 재설정


def test_admin_reset_sets_temporary_password_without_returning_it(admin) -> None:
    alice = make_user(admin, "alice")
    session = session_client("alice")
    reset = admin.post(f"/api/users/{alice}/reset-password", json={"temporary_password": NEW_PW})
    assert reset.status_code == 200
    assert NEW_PW not in reset.text
    assert reset.json()["must_change_password"] is True
    assert session.get("/api/auth/me").status_code == 401
    assert login(make_client(), "alice", PW).status_code == 401
    client = session_client("alice", NEW_PW)
    assert client.get("/api/dashboard").status_code == 403
    assert (
        client.post(
            "/api/auth/password", json={"current_password": NEW_PW, "new_password": PW}
        ).status_code
        == 200
    )
    assert client.get("/api/dashboard").status_code == 200


# 권한


def test_existing_routes_follow_the_permission_grants(url, admin) -> None:
    alice = make_user(admin, "alice")
    client = session_client("alice")
    assert client.get("/api/alerts").status_code == 200
    assert client.get("/api/ticketing-policy").status_code == 200
    body = {"mode": "auto", "scenario_rule_ids": []}
    assert client.put("/api/ticketing-policy", json=body).status_code == 403
    assert admin.put("/api/ticketing-policy", json=body).status_code == 200
    revoked = [p for p in ANALYST_DEFAULT if p != "alert.read"]
    assert (
        admin.put(f"/api/users/{alice}/permissions", json={"permissions": revoked}).status_code
        == 200
    )
    assert client.get("/api/alerts").status_code == 403
    assert client.get("/api/events").status_code == 200
    granted = [*revoked, "policy.update", "incident.approve"]
    response = admin.put(f"/api/users/{alice}/permissions", json={"permissions": granted})
    assert response.json()["permissions"] == sorted(granted)
    assert client.put("/api/ticketing-policy", json=body).status_code == 200
    assert perms(admin, alice) == sorted(granted)


def test_unknown_permission_name_is_422(admin) -> None:
    alice = make_user(admin, "alice")
    response = admin.put(f"/api/users/{alice}/permissions", json={"permissions": ["alert.write"]})
    assert (response.status_code, response.json()) == (
        422,
        {"error": "invalid_body", "fields": ["permissions"]},
    )


def test_escalation_rules(url, admin) -> None:
    admin_id = user_id(admin, "admin")
    alice, bob = make_user(admin, "alice"), make_user(admin, "bob")
    other_admin = make_user(admin, "carol", "admin")
    helper = ["user.read", "user.approve", "user.permission", "alert.read"]
    assert (
        admin.put(f"/api/users/{bob}/permissions", json={"permissions": helper}).status_code == 200
    )
    b = session_client("bob")

    def put(target: str, names: list[str]):
        return b.put(f"/api/users/{target}/permissions", json={"permissions": names})

    forbidden = {"error": "forbidden"}
    assert put(bob, helper).json() == forbidden  # 규칙 4: 자기 자신
    assert put(alice, ["alert.read", "policy.update"]).json() == forbidden  # 규칙 3: 없는 권한
    assert put(alice, ["alert.read"]).json()["permissions"] == ["alert.read"]  # 줄이는 것은 가능
    assert put(admin_id, []).json() == forbidden  # 규칙 1: admin 대상
    assert b.post(f"/api/users/{admin_id}/disable").json() == forbidden
    assert (
        b.post(
            f"/api/users/{other_admin}/reset-password", json={"temporary_password": NEW_PW}
        ).json()
        == forbidden
    )
    assert b.patch(f"/api/users/{other_admin}", json={"role": "analyst"}).json() == forbidden
    assert b.patch(f"/api/users/{alice}", json={"role": "admin"}).json() == forbidden  # 규칙 2
    assert signup("dave.ops").status_code == 201
    dave = user_id(admin, "dave.ops")
    assert b.post(f"/api/users/{dave}/approve", json={"role": "admin"}).json() == forbidden
    assert b.post(f"/api/users/{dave}/approve", json={"role": "analyst"}).status_code == 200
    # admin은 가진 권한이 전체라 권한 행을 바꿀 수 없다
    assert admin.put(f"/api/users/{other_admin}/permissions", json={"permissions": []}).json() == {
        "error": "invalid_target"
    }
    assert sql(url, "SELECT count(*) FROM user_permissions WHERE user_id = %s", (other_admin,)) == [
        (0,)
    ]


def test_permission_changes_apply_to_the_next_request_without_new_login(admin) -> None:
    alice = make_user(admin, "alice")
    client = session_client("alice")
    assert client.get("/api/users").status_code == 403
    admin.put(f"/api/users/{alice}/permissions", json={"permissions": ["user.read"]})
    assert client.get("/api/users").status_code == 200
    admin.put(f"/api/users/{alice}/permissions", json={"permissions": []})
    assert client.get("/api/users").status_code == 403
    assert client.get("/api/auth/me").json()["permissions"] == []


# 비밀


def test_agent_reader_cannot_read_auth_tables(url) -> None:
    with psycopg.connect(url, autocommit=True) as conn:
        conn.execute("SET ROLE soc_agent_reader")
        for table in ("users", "user_sessions", "user_permissions"):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                conn.execute(f"SELECT count(*) FROM {table}")


def test_passwords_and_tokens_stay_out_of_logs_responses_and_database(
    url, admin, caplog, capsys
) -> None:
    with caplog.at_level(logging.DEBUG):
        alice = make_user(admin, "alice")
        client = session_client("alice")
        token = client.cookies.get("soc_session")
        responses = [
            client.get("/api/auth/me"),
            client.post(
                "/api/auth/password", json={"current_password": PW, "new_password": NEW_PW}
            ),
            login(make_client(), "alice", "wrong-" + PW),
            admin.post(f"/api/users/{alice}/reset-password", json={"temporary_password": PW}),
            admin.get("/api/users"),
        ]
    secrets = (PW, NEW_PW, "wrong-" + PW, token)
    for secret in secrets:
        assert secret not in caplog.text
        assert secret not in capsys.readouterr().out
        for response in responses:
            assert secret not in response.text
    dump = json.dumps(sql(url, "SELECT * FROM users"), default=str)
    assert PW not in dump and NEW_PW not in dump
