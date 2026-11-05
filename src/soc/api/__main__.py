"""`uv run python -m soc.api`: 화면용 API를 uvicorn으로 띄운다(#239).

종료 코드: 0 정상 종료, 2 설정 오류(DATABASE_URL 없음 포함). DB 주소는 출력하지 않는다.
"""

import os
import sys

import uvicorn

from soc.api.app import create_app
from soc.api.config import ConfigError, load_settings
from soc.api.db import DATABASE_URL_ENV


def main() -> int:
    if not os.environ.get(DATABASE_URL_ENV):
        print(f"환경변수 {DATABASE_URL_ENV}가 필요하다")
        return 2
    try:
        settings = load_settings()
    except ConfigError as exc:
        print(f"설정 오류: {exc}")
        return 2
    uvicorn.run(create_app(settings), host=settings.host, port=settings.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
