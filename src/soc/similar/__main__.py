"""uv run python -m soc.similar reindex [--recreate]."""

import argparse
import os
import sys
import tomllib

from soc.agent.config import load_full_config
from soc.similar.index import PURPOSE, reindex
from soc.store import BgeM3Embedder, ConfigError, VectorStore
from soc.store.config import read_settings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m soc.similar", description="유사 사례 색인 명령"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("reindex", help="판정이 있는 Ticket을 색인한다")
    command.add_argument(
        "--recreate",
        action="store_true",
        help="현재 설정의 컬렉션을 지우고 전체 색인을 다시 만든다",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        config = load_full_config()
        settings = read_settings(config["store"])
        database_url = os.environ.get("DATABASE_URL")
        if not database_url:
            raise ConfigError("DATABASE_URL이 필요하다")
    except (ConfigError, KeyError, OSError, tomllib.TOMLDecodeError) as exc:
        print(f"설정 오류({type(exc).__name__})", file=sys.stderr)
        return 2

    try:
        embedder = BgeM3Embedder(settings.embedder)
        store = VectorStore(PURPOSE, embedder, settings)
        result = reindex(database_url, embedder, store, recreate=args.recreate)
    except Exception as exc:
        print(f"재색인 실패({type(exc).__name__})", file=sys.stderr)
        return 1

    names = ("processed", "succeeded", "skipped", "failed")
    print(" ".join(f"{name}={result[name]}" for name in names))
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
