"""uv run python -m soc.l3 hunt: L3 가설 헌팅을 한 번 돌린다(#223).

DB 주소는 환경변수 DATABASE_URL이다. 마이그레이션은 하지 않는다
(uv run python -m soc.db.migrate를 먼저 실행한다). 수집만 하려면 uv run python -m soc.l3.intel.
종료 코드: 0 정상, 1 가설 생성 run 실패 또는 DB 오류, 2 설정 오류.
"""

import argparse
import os
import sys

from soc.l3.config import load_config
from soc.l3.hunt.command import run_hunt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m soc.l3", description="L3 위협 헌팅")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("hunt", help="수집 → 가설 생성 → pending Hunt 검증")
    parser.parse_args(argv)
    return run_hunt(
        load_config()["l3"],
        os.environ.get("DATABASE_URL"),
        err=lambda line: print(line, file=sys.stderr),
    )


if __name__ == "__main__":
    sys.exit(main())
