"""사용자·세션·권한 SQL과 규칙(#284, D-020).

- 함수는 dict_row 연결을 받는다. 쓰기 함수는 자기 트랜잭션을 연다.
- 사용자 수를 바꾸거나 권한을 바꾸는 작업은 같은 advisory 락 아래에서 직렬화한다. 최초 admin 중복
  생성과 마지막 admin 보호가 동시 요청에서도 지켜진다.
- 권한 상승 방지(계획 284): ①admin 계정을 대상으로 하는 작업은 admin만, ②admin 역할 지정은 admin만,
  ③권한은 부여자가 가진 것만 남에게 준다, ④자기 권한은 바꾸지 못한다, ⑤마지막 admin은 지킨다.
  가입 승인 때 analyst가 받는 기본 조회 권한은 승인자 권한과 관계없이 시스템이 준다.
- 비밀번호·토큰 원문은 밖으로 나가는 값(최초 임시 비밀번호, 새 세션 토큰) 말고는 남기지 않는다.
"""

import hashlib
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg.errors import UniqueViolation

from soc.auth import passwords
from soc.auth.permissions import ANALYST_DEFAULT, PERMISSIONS
from soc.contracts import to_epoch_ms

# "soc.auth.users"의 SHA-256 앞 8바이트를 부호 있는 64비트 정수(big-endian)로 읽은 값.
# 마이그레이션 실행기의 잠금 키와 겹치지 않는다
LOCK_KEY = 5389736483619737918

FIRST_ADMIN = "admin"
_COLUMNS = "id, username, display_name, role, status, must_change_password, created_at, approved_at"


class AuthError(Exception):
    """상태 코드와 오류 코드만 가진다. 입력값은 담지 않는다."""

    def __init__(self, status: int, code: str) -> None:
        super().__init__(code)
        self.status = status
        self.code = code


@dataclass(frozen=True)
class User:
    id: str
    username: str
    display_name: str
    role: str
    must_change_password: bool
    permissions: frozenset[str]


# 세션


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _lock(conn: psycopg.Connection) -> None:
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (LOCK_KEY,))


def _open_session(conn: psycopg.Connection, user_id: Any, idle: int, absolute: int) -> str:
    # 이 사용자의 만료된 세션을 지운다(만료 행이 쌓이지 않게)
    conn.execute(
        "DELETE FROM user_sessions WHERE user_id = %s AND (expires_at <= now() "
        "OR last_seen_at <= now() - make_interval(secs => %s))",
        (user_id, idle),
    )
    token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO user_sessions (token_hash, user_id, expires_at) "
        "VALUES (%s, %s, now() + make_interval(secs => %s))",
        (token_hash(token), user_id, absolute),
    )
    return token


def _delete_sessions(conn: psycopg.Connection, user_id: Any) -> None:
    conn.execute("DELETE FROM user_sessions WHERE user_id = %s", (user_id,))


def find_session_user(conn: psycopg.Connection, token: str, idle: int) -> User | None:
    """유효한 세션이면 마지막 사용 시각을 갱신하고 사용자와 현재 권한을 돌려준다."""
    with conn.transaction():
        row = conn.execute(
            "UPDATE user_sessions s SET last_seen_at = now() FROM users u "
            "WHERE s.token_hash = %s AND u.id = s.user_id AND u.status = 'active' "
            "AND s.expires_at > now() AND s.last_seen_at > now() - make_interval(secs => %s) "
            "RETURNING u.id, u.username, u.display_name, u.role, u.must_change_password",
            (token_hash(token), idle),
        ).fetchone()
        if row is None:
            return None
        if row["role"] == "admin":
            granted = frozenset(PERMISSIONS)
        else:
            granted = frozenset(
                r["permission"]
                for r in conn.execute(
                    "SELECT permission FROM user_permissions WHERE user_id = %s", (row["id"],)
                )
            )
    return User(
        id=str(row["id"]),
        username=row["username"],
        display_name=row["display_name"],
        role=row["role"],
        must_change_password=row["must_change_password"],
        permissions=granted,
    )


def logout(conn: psycopg.Connection, token: str) -> None:
    with conn.transaction():
        conn.execute("DELETE FROM user_sessions WHERE token_hash = %s", (token_hash(token),))


# 사용자 레코드


def _records(conn: psycopg.Connection, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    granted: dict[Any, list[str]] = {}
    for r in conn.execute(
        "SELECT user_id, permission FROM user_permissions WHERE user_id = ANY(%s)",
        ([row["id"] for row in rows],),
    ):
        granted.setdefault(r["user_id"], []).append(r["permission"])
    return [
        {
            "id": str(row["id"]),
            "username": row["username"],
            "display_name": row["display_name"],
            "role": row["role"],
            "status": row["status"],
            "must_change_password": row["must_change_password"],
            "permissions": sorted(PERMISSIONS)
            if row["role"] == "admin"
            else sorted(granted.get(row["id"], [])),
            "created_at": to_epoch_ms(row["created_at"]),
            "approved_at": to_epoch_ms(row["approved_at"]) if row["approved_at"] else None,
        }
        for row in rows
    ]


def get_record(conn: psycopg.Connection, user_id: Any) -> dict[str, Any]:
    row = conn.execute(f"SELECT {_COLUMNS} FROM users WHERE id = %s", (user_id,)).fetchone()
    if row is None:
        raise AuthError(404, "not_found")
    return _records(conn, [row])[0]


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_CURSOR = re.compile(
    r"([0-9]{1,17})_([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})"
)


def decode_cursor(text: str) -> tuple[datetime, uuid.UUID]:
    """`<만든 시각 마이크로초>_<ID>`. 모양이 틀리면 ValueError다."""
    match = _CURSOR.fullmatch(text)
    if match is None:
        raise ValueError("cursor")
    return _EPOCH + timedelta(microseconds=int(match[1])), uuid.UUID(match[2])


def _encode_cursor(row: dict[str, Any]) -> str:
    return f"{(row['created_at'] - _EPOCH) // timedelta(microseconds=1)}_{row['id']}"


def list_records(
    conn: psycopg.Connection,
    status: str | None,
    after: tuple[datetime, uuid.UUID] | None,
    limit: int,
) -> tuple[list[dict[str, Any]], str | None]:
    """만든 순서로 limit건과 다음 cursor(없으면 None)를 돌려준다."""
    rows = conn.execute(
        f"SELECT {_COLUMNS} FROM users WHERE (%s::text IS NULL OR status = %s) "
        "AND (%s::timestamptz IS NULL OR (created_at, id) > (%s, %s)) "
        "ORDER BY created_at, id LIMIT %s",
        (status, status, after and after[0], after and after[0], after and after[1], limit + 1),
    ).fetchall()
    page = rows[:limit]
    next_cursor = _encode_cursor(page[-1]) if len(rows) > limit else None
    return (_records(conn, page) if page else []), next_cursor


# 가입·로그인·비밀번호


def signup(conn: psycopg.Connection, username: str, display_name: str, password: str) -> None:
    hashed = passwords.hash_password(password)
    try:
        with conn.transaction():
            conn.execute(
                "INSERT INTO users (username, display_name, password_hash, status) "
                "VALUES (%s, %s, %s, 'pending')",
                (username, display_name, hashed),
            )
    except UniqueViolation:
        raise AuthError(409, "username_taken") from None


def login(
    conn: psycopg.Connection, username: str, password: str, idle: int, absolute: int
) -> tuple[str, dict[str, Any]]:
    # 첫 쿼리 전에 트랜잭션을 연다. 암묵 트랜잭션이 열려 있으면 savepoint가 되어 커밋되지 않는다
    with conn.transaction():
        row = conn.execute(
            "SELECT id, password_hash, status FROM users WHERE username = %s", (username,)
        ).fetchone()
        # 없는 아이디도 더미 해시를 검증해 응답 시간 차이를 줄인다
        hashed = row["password_hash"] if row else passwords.DUMMY_HASH
        matched = passwords.verify_password(hashed, password)
        if row is None or not matched:
            raise AuthError(401, "invalid_credentials")
        if row["status"] != "active":
            raise AuthError(403, f"account_{row['status']}")
        return _open_session(conn, row["id"], idle, absolute), get_record(conn, row["id"])


def change_password(
    conn: psycopg.Connection, user: User, current: str, new: str, idle: int, absolute: int
) -> tuple[str, dict[str, Any]]:
    hashed = passwords.hash_password(new)
    with conn.transaction():
        row = conn.execute("SELECT password_hash FROM users WHERE id = %s", (user.id,)).fetchone()
        if row is None or not passwords.verify_password(row["password_hash"], current):
            raise AuthError(401, "invalid_credentials")
        conn.execute(
            "UPDATE users SET password_hash = %s, must_change_password = false WHERE id = %s",
            (hashed, user.id),
        )
        _delete_sessions(conn, user.id)  # 다른 세션은 끝내고 현재 세션은 새 토큰으로 바꾼다
        return _open_session(conn, user.id, idle, absolute), get_record(conn, user.id)


# 최초 관리자


def ensure_first_admin(conn: psycopg.Connection) -> str | None:
    """사용자가 0명이면 admin을 만들고 임시 비밀번호를 돌려준다. 이미 있으면 None이다."""
    with conn.transaction():
        _lock(conn)
        if conn.execute("SELECT count(*) AS n FROM users").fetchone()["n"]:
            return None
        temporary = secrets.token_urlsafe(18)
        conn.execute(
            "INSERT INTO users (username, display_name, password_hash, role, status, "
            "must_change_password, approved_at) "
            "VALUES (%s, 'admin', %s, 'admin', 'active', true, now())",
            (FIRST_ADMIN, passwords.hash_password(temporary)),
        )
        return temporary


# 사용자 관리


def _target(conn: psycopg.Connection, target: uuid.UUID) -> dict[str, Any]:
    row = conn.execute(f"SELECT {_COLUMNS} FROM users WHERE id = %s", (target,)).fetchone()
    if row is None:
        raise AuthError(404, "not_found")
    return row


def _admin_only_target(actor: User, row: dict[str, Any]) -> None:
    if row["role"] == "admin" and actor.role != "admin":  # 규칙 1
        raise AuthError(403, "forbidden")


def _not_last_admin(conn: psycopg.Connection, row: dict[str, Any]) -> None:
    if row["role"] == "admin" and row["status"] == "active":
        active = conn.execute(
            "SELECT count(*) AS n FROM users WHERE role = 'admin' AND status = 'active'"
        ).fetchone()["n"]
        if active <= 1:  # 규칙 5
            raise AuthError(409, "last_admin")


def _reset_permissions(conn: psycopg.Connection, user_id: Any, role: str, by: str) -> None:
    conn.execute("DELETE FROM user_permissions WHERE user_id = %s", (user_id,))
    if role == "analyst":
        conn.execute(
            "INSERT INTO user_permissions (user_id, permission, granted_by) "
            "SELECT %s, p, %s FROM unnest(%s::text[]) AS p",
            (user_id, by, list(ANALYST_DEFAULT)),
        )


def approve(conn: psycopg.Connection, actor: User, target: uuid.UUID, role: str) -> dict[str, Any]:
    with conn.transaction():
        _lock(conn)
        row = _target(conn, target)
        if role == "admin" and actor.role != "admin":  # 규칙 2
            raise AuthError(403, "forbidden")
        if row["status"] != "pending":
            raise AuthError(409, "invalid_state")
        conn.execute(
            "UPDATE users SET status = 'active', role = %s, approved_at = now(), approved_by = %s "
            "WHERE id = %s",
            (role, actor.id, target),
        )
        _reset_permissions(conn, target, role, actor.id)
        return get_record(conn, target)


def reject(conn: psycopg.Connection, actor: User, target: uuid.UUID) -> dict[str, Any]:
    with conn.transaction():
        _lock(conn)
        row = _target(conn, target)
        if row["status"] != "pending":
            raise AuthError(409, "invalid_state")
        conn.execute("UPDATE users SET status = 'rejected' WHERE id = %s", (target,))
        return get_record(conn, target)


def disable(conn: psycopg.Connection, actor: User, target: uuid.UUID) -> dict[str, Any]:
    with conn.transaction():
        _lock(conn)
        row = _target(conn, target)
        _admin_only_target(actor, row)
        if row["status"] != "active":
            raise AuthError(409, "invalid_state")
        _not_last_admin(conn, row)
        conn.execute("UPDATE users SET status = 'disabled' WHERE id = %s", (target,))
        _delete_sessions(conn, target)
        return get_record(conn, target)


def reset_password(
    conn: psycopg.Connection, actor: User, target: uuid.UUID, temporary: str
) -> dict[str, Any]:
    hashed = passwords.hash_password(temporary)
    with conn.transaction():
        _lock(conn)
        row = _target(conn, target)
        _admin_only_target(actor, row)
        if row["status"] != "active":
            raise AuthError(409, "invalid_state")
        conn.execute(
            "UPDATE users SET password_hash = %s, must_change_password = true WHERE id = %s",
            (hashed, target),
        )
        _delete_sessions(conn, target)
        return get_record(conn, target)


def set_role(conn: psycopg.Connection, actor: User, target: uuid.UUID, role: str) -> dict[str, Any]:
    # 역할 변경은 admin 전용이다(권한으로 위임하지 않는다). 라우트도 require_role로 막는다
    if actor.role != "admin":
        raise AuthError(403, "forbidden")
    with conn.transaction():
        _lock(conn)
        row = _target(conn, target)
        if row["status"] != "active":
            raise AuthError(409, "invalid_state")
        if row["role"] == role:
            return get_record(conn, target)
        if role == "analyst":
            _not_last_admin(conn, row)
        conn.execute("UPDATE users SET role = %s WHERE id = %s", (role, target))
        _reset_permissions(conn, target, role, actor.id)
        _delete_sessions(conn, target)
        return get_record(conn, target)


def set_permissions(
    conn: psycopg.Connection, actor: User, target: uuid.UUID, names: list[str]
) -> dict[str, Any]:
    if str(target) == actor.id:  # 규칙 4
        raise AuthError(403, "forbidden")
    wanted = set(names)
    with conn.transaction():
        _lock(conn)
        row = _target(conn, target)
        _admin_only_target(actor, row)
        if row["role"] == "admin" or row["status"] != "active":
            raise AuthError(409, "invalid_target")
        current = {
            r["permission"]
            for r in conn.execute(
                "SELECT permission FROM user_permissions WHERE user_id = %s", (target,)
            )
        }
        added = wanted - current
        if not added <= actor.permissions:  # 규칙 3: 줄이는 것은 누구나, 늘리는 것은 가진 만큼만
            raise AuthError(403, "forbidden")
        conn.execute(
            "DELETE FROM user_permissions WHERE user_id = %s AND permission = ANY(%s)",
            (target, list(current - wanted)),
        )
        conn.execute(
            "INSERT INTO user_permissions (user_id, permission, granted_by) "
            "SELECT %s, p, %s FROM unnest(%s::text[]) AS p",
            (target, actor.id, sorted(added)),
        )
        return get_record(conn, target)
