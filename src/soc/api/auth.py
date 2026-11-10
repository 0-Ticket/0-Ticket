"""요청 인증·권한·CSRF(#284, D-020).

- 라우트 보호는 의존성으로 한다: session_user(로그인) → active_user(임시 비밀번호 변경 전이면 막음)
  → require_permission(권한). 앱 조립(app.py)이 `/api` 라우터에 active_user를 기본으로 건다.
- 인증은 요청마다 쓰기 연결로 세션을 읽고 last_seen_at을 갱신한다. 데이터 라우트는 읽기 연결이다.
- 오류 본문에는 오류 코드만 넣는다. 토큰·비밀번호는 로그에도 본문에도 남기지 않는다.
"""

from typing import Annotated

from fastapi import Depends, FastAPI, Request
from fastapi.responses import JSONResponse

from soc.api import db
from soc.auth import store
from soc.auth.permissions import PERMISSIONS
from soc.auth.store import AuthError, User

# 라우트에 붙은 권한 이름. 목록의 모든 권한이 쓰이는지 테스트가 본다(승인류 3개는 예외)
USED_PERMISSIONS: set[str] = set()

_SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def session_user(request: Request) -> User:
    settings = request.app.state.settings
    token = request.cookies.get(settings.auth.cookie_name)
    if not token:
        raise AuthError(401, "unauthenticated")
    with db.connect_write(settings) as conn:
        user = store.find_session_user(conn, token, settings.auth.idle_timeout_seconds)
    if user is None:
        raise AuthError(401, "unauthenticated")
    return user


def active_user(user: Annotated[User, Depends(session_user)]) -> User:
    if user.must_change_password:
        raise AuthError(403, "password_change_required")
    return user


def require_permission(name: str):
    if name not in PERMISSIONS:
        raise ValueError(f"알 수 없는 권한 이름이다: {name}")
    USED_PERMISSIONS.add(name)

    def check(user: Annotated[User, Depends(active_user)]) -> User:
        if name not in user.permissions:
            raise AuthError(403, "permission_denied")
        return user

    return check


def require_role(role: str):
    """admin 전용 같은 역할 검사. 일반 라우트는 require_permission을 쓴다."""

    def check(user: Annotated[User, Depends(active_user)]) -> User:
        if user.role != role:
            raise AuthError(403, "forbidden")
        return user

    return check


def install_csrf(app: FastAPI) -> None:
    """POST/PUT/PATCH/DELETE는 Origin이 허용 목록에 없으면 거부한다(없어도 거부)."""
    allowed = set(app.state.settings.auth.allowed_origins)

    async def csrf(request: Request, call_next):
        if request.method not in _SAFE_METHODS and request.headers.get("origin") not in allowed:
            return JSONResponse({"error": "origin_not_allowed"}, status_code=403)
        return await call_next(request)

    app.middleware("http")(csrf)
