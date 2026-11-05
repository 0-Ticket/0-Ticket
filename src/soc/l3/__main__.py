"""uv run python -m soc.l3 <명령>: L3 위협 헌팅.

- hunt: L3 가설 헌팅을 한 번 돌린다(#223). 종료 코드: 0 정상, 1 가설 생성 run 실패 또는 DB 오류,
  2 설정 오류.
- dev-seed [--remove]: 개발 DB 전용 시드를 지우고 다시 넣는다(--remove는 지우기만, #224).
  종료 코드: 0 정상, 1 시드가 Incident에 붙어 지우지 않음 또는 DB 오류, 2 DATABASE_URL·샘플 오류.

DB 주소는 환경변수 DATABASE_URL이다. 마이그레이션은 하지 않는다
(uv run python -m soc.db.migrate를 먼저 실행한다). 수집만 하려면 uv run python -m soc.l3.intel.
"""

import argparse
import os
import sys

from soc.l3.config import load_config
from soc.l3.hunt.command import run_hunt
from soc.l3.hunt.dev_seed import run_dev_seed

DEV_SEED_HELP = (
    "개발 DB 전용. tests/fixtures/l3_hunt/dev_seed.json의 시드(위협 있음·없음 pending Hunt 2개와"
    " 근거 Alert·Event)를 지우고 다시 넣는다. 운영 DB에 쓰지 않는다"
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m soc.l3", description="L3 위협 헌팅")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("hunt", help="수집 → 가설 생성 → pending Hunt 검증")
    dev_seed = commands.add_parser(
        "dev-seed", help="개발 DB 전용 시드 넣기·지우기", description=DEV_SEED_HELP
    )
    dev_seed.add_argument(
        "--remove", action="store_true", help="시드 행만 지우고 새로 넣지 않는다(Agent Log는 남김)"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    database_url = os.environ.get("DATABASE_URL")

    def err(line: str) -> None:
        print(line, file=sys.stderr)

    if args.command == "dev-seed":
        return run_dev_seed(database_url, remove=args.remove, err=err)
    return run_hunt(load_config()["l3"], database_url, err=err)


if __name__ == "__main__":
    sys.exit(main())
