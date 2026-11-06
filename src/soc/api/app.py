"""화면용 API 앱(FastAPI, D-016, #239).

- 라우터는 routes/ 아래 파일별로 두고 /api 접두사 라우터 하나에 묶는다.
- W04 정책 라우터는 인증 없이 연결된다. 접근 제어는 D-020 후속 작업이다.
- 헌팅·대응을 실행하는 API는 만들지 않는다(docs/security.md "화면").
- /docs·/redoc은 끈다(Swagger UI는 외부 CDN 스크립트를 받는다). /openapi.json은 둔다.
"""

from fastapi import APIRouter, FastAPI

from soc.api import errors
from soc.api.config import ApiSettings
from soc.api.routes import dashboard, hunts, records, threat_news, ticketing_policy, workflow


def create_app(settings: ApiSettings) -> FastAPI:
    app = FastAPI(title="0-Ticket SOC API", docs_url=None, redoc_url=None)
    app.state.settings = settings
    api = APIRouter(prefix="/api")
    api.include_router(dashboard.router)
    api.include_router(records.router)
    api.include_router(workflow.router)
    api.include_router(hunts.router)
    api.include_router(threat_news.router)
    api.include_router(ticketing_policy.router)
    app.include_router(api)
    errors.install(app)
    return app
