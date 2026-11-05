"""화면용 API 앱(FastAPI, D-016, #239). 읽기 전용 GET만 둔다.

- 라우터는 routes/ 아래 파일별로 두고 /api 접두사 라우터 하나에 묶는다.
  인증(D-020) 이슈가 이 라우터에 붙인다.
- 헌팅·대응을 실행하는 API는 만들지 않는다(docs/security.md "화면").
- /docs·/redoc은 끈다(Swagger UI는 외부 CDN 스크립트를 받는다). /openapi.json은 둔다.
"""

from fastapi import APIRouter, FastAPI

from soc.api import errors
from soc.api.config import ApiSettings
from soc.api.routes import hunts, threat_news


def create_app(settings: ApiSettings) -> FastAPI:
    app = FastAPI(title="0-Ticket SOC API", docs_url=None, redoc_url=None)
    app.state.settings = settings
    api = APIRouter(prefix="/api")
    api.include_router(hunts.router)
    api.include_router(threat_news.router)
    app.include_router(api)
    errors.install(app)
    return app
