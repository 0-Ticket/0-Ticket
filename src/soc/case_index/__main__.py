"""uv run python -m soc.case_index check | reindex [--recreate] (#391, D-084).

출력은 건수만이다. 오류는 종류(예외 클래스 이름)만 표시하고 주소·Case 문장은 내지 않는다.
종료 코드: 0 정상, 1 빠진 Case가 있거나 실패, 2 설정 오류.
check는 missing·no_job·pending 중 하나라도 있으면 1이다(no_artifact는 정보 표시).
"""

import argparse
import os
import sys
import tomllib

from soc.case_index.index import check, reindex
from soc.case_index.source import PURPOSE
from soc.store import BgeM3Embedder, ConfigError, VectorStore
from soc.store.config import load_config, read_settings

CHECK_KEYS = ("cases", "missing", "no_job", "pending", "no_artifact")
REINDEX_KEYS = ("processed", "succeeded", "failed")
GAP_KEYS = ("missing", "no_job", "pending")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m soc.case_index", description="승인된 Case 색인 명령"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="Case와 대기 행·point를 대조해 빠진 건수를 보인다")
    command = commands.add_parser("reindex", help="모든 Case를 다시 색인한다")
    command.add_argument(
        "--recreate",
        action="store_true",
        help="현재 설정의 컬렉션을 지우고 전체 색인을 다시 만든다",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        settings = read_settings(load_config()["store"])
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise ConfigError("DATABASE_URL이 필요하다")
    except (ConfigError, KeyError, OSError, tomllib.TOMLDecodeError) as exc:
        print(f"설정 오류({type(exc).__name__})", file=sys.stderr)
        return 2

    try:
        embedder = BgeM3Embedder(settings.embedder)
        store = VectorStore(PURPOSE, embedder, settings)
        if args.command == "check":
            result = check(database_url, store)
            keys = CHECK_KEYS
            code = 1 if any(result[key] for key in GAP_KEYS) else 0
        else:
            result = reindex(database_url, embedder, store, recreate=args.recreate)
            keys = REINDEX_KEYS
            code = 1 if result["failed"] else 0
    except Exception as exc:
        print(f"{args.command} 실패({type(exc).__name__})", file=sys.stderr)
        return 1

    print(" ".join(f"{key}={result[key]}" for key in keys))
    return code


if __name__ == "__main__":
    sys.exit(main())
