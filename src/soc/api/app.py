"""화면용 API 앱(FastAPI, D-016, #239).

- 라우터는 routes/ 아래 파일별로 두고 /api 접두사 라우터에 묶는다.
- 기본 거부(#284): /api 라우터는 로그인(active_user)을 기본으로 요구한다. 인증 없이 열리는 것은
  public 라우터의 로그인·가입뿐이다. 라우트마다 require_permission으로 권한을 요구한다.
  me·logout·password는 임시 비밀번호를 바꾸기 전에도 쓰므로 session 라우터에 따로 둔다.
- 변경 요청(POST/PUT/PATCH/DELETE)은 Origin 허용 목록을 검사한다(설정 [auth] allowed_origins).
- 헌팅·대응을 실행하는 API는 만들지 않는다(docs/security.md "화면").
- /docs·/redoc은 끈다(Swagger UI는 외부 CDN 스크립트를 받는다). OpenAPI 문서는 로그인해야 받는
  /api/openapi.json에 둔다.
"""

from fastapi import APIRouter, Depends, FastAPI

from soc.api import errors
from soc.api.auth import active_user, install_csrf, session_user
from soc.api.config import ApiSettings
from soc.api.routes import (
    auth,
    dashboard,
    hunts,
    records,
    threat_news,
    ticketing_policy,
    users,
    workflow,
)


def create_app(settings: ApiSettings) -> FastAPI:
    app = FastAPI(title="0-Ticket SOC API", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.settings = settings

    public = APIRouter(prefix="/api")
    public.include_router(auth.public)

    session = APIRouter(prefix="/api", dependencies=[Depends(session_user)])
    session.include_router(auth.session)

    api = APIRouter(prefix="/api", dependencies=[Depends(active_user)])
    for router in (
        dashboard.router,
        records.router,
        workflow.router,
        hunts.router,
        threat_news.router,
        ticketing_policy.router,
        users.router,
    ):
        api.include_router(router)

    @api.get("/openapi.json", include_in_schema=False)
    def openapi() -> dict:
        return app.openapi()

    for router in (public, session, api):
        app.include_router(router)
    errors.install(app)
    install_csrf(app)
    return app
