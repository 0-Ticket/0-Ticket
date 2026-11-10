"""인증이 걸린 화면용 API를 테스트하는 도우미(#284).

DB 없는 테스트는 session_user 의존성을 바꿔 사용자와 권한을 넣는다. 인증·세션 동작 자체는
test_auth_db.py가 실제 로그인으로 확인한다.
"""

from starlette.testclient import TestClient

from soc.api.app import create_app
from soc.api.auth import session_user
from soc.api.config import ApiSettings, load_settings
from soc.auth.permissions import PERMISSIONS
from soc.auth.store import User

ORIGIN = "http://127.0.0.1:5173"


def make_user(
    role: str = "admin",
    permissions: frozenset[str] | None = None,
    *,
    must_change_password: bool = False,
) -> User:
    if permissions is None:
        permissions = frozenset(PERMISSIONS) if role == "admin" else frozenset()
    return User(
        id="00000000-0000-4000-8000-000000000001",
        username="tester",
        display_name="Tester",
        role=role,
        must_change_password=must_change_password,
        permissions=permissions,
    )


def make_client(
    user: User | None = None, settings: ApiSettings | None = None, **kwargs: object
) -> TestClient:
    """허용 Origin을 기본으로 보내는 클라이언트. user가 있으면 로그인한 것으로 본다."""
    app = create_app(settings or load_settings())
    if user is not None:
        app.dependency_overrides[session_user] = lambda: user
    return TestClient(app, headers={"origin": ORIGIN}, **kwargs)


def admin_client(**kwargs: object) -> TestClient:
    return make_client(make_user("admin"), **kwargs)
