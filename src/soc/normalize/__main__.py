"""정규화를 한 번 실행하고 끝낸다. 주기 실행은 cron이 한다.

    uv run python -m soc.normalize
    uv run python -m soc.normalize report   # 소스별 채움률(읽기 전용, 건수만)
    uv run python -m soc.normalize reprocess [--kind alert|event] [--source S] [--since T]
        [--limit N] [--dry-run]
    # 이미 정규화된 알럿(기본) 또는 이벤트를 id를 유지한 채 다시 정규화한다(#334, #347)

종료 코드: 0 실패 없음, 1 실패한 건이 있거나 DB에 접속·조회하지 못함, 2 설정·환경변수 오류.
"""

import argparse
import os
import sys
import tomllib
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import psycopg

from soc.api.db import DATABASE_URL_ENV
from soc.normalize.config import ConfigError, Settings, load_settings
from soc.normalize.report import report_lines
from soc.normalize.reprocess import exit_code as reprocess_exit_code
from soc.normalize.reprocess import format_result as format_reprocess
from soc.normalize.reprocess import reprocess
from soc.normalize.run import RunResult, exit_code, run
from soc.normalize.tables import MappingTableError, load_tables


def main(argv: list[str] | None = None) -> int:
    """설정을 읽고 연결을 열어 정규화를 한 번 실행한다. `report`면 채움률만 낸다.

    Args:
        argv: 명령 인자. 없으면 정규화를 실행한다.
    """
    if argv == ["report"]:
        return _report_command()
    if argv and argv[0] == "reprocess":
        return _reprocess_command(argv[1:])
    if argv:
        print("사용법: python -m soc.normalize [report | reprocess]", file=sys.stderr)
        return 2
    return _run_command(run)


def _report_command() -> int:
    """소스별 채움률을 읽어 출력한다."""
    url = os.environ.get(DATABASE_URL_ENV)
    if not url:
        print(f"환경변수 {DATABASE_URL_ENV}가 필요하다", file=sys.stderr)
        return 2
    try:
        with psycopg.connect(url, autocommit=True, connect_timeout=5) as conn:
            lines = report_lines(conn)
    except psycopg.Error:
        print("DB에 접속하지 못했거나 조회에 실패했다", file=sys.stderr)
        return 1
    print("\n".join(lines))
    return 0


def _reprocess_command(argv: list[str]) -> int:
    """재처리 옵션을 읽어 알럿(또는 이벤트)을 다시 정규화한다. 옵션이 틀리면 종료 코드 2다."""
    parser = argparse.ArgumentParser(prog="python -m soc.normalize reprocess")
    parser.add_argument(
        "--kind",
        choices=("alert", "event"),
        default="alert",
        help="다시 정규화할 종류. 기본은 alert",
    )
    parser.add_argument(
        "--source", help="새 결과의 소스(modsecurity, suricata 등)가 같은 알럿만(--kind alert 전용)"
    )
    parser.add_argument(
        "--since", type=_since, help="alerts.time이 이 시각 이후인 알럿만(ISO 8601)"
    )
    parser.add_argument(
        "--all", action="store_true", help="outcome과 관계없이 기존 알럿 전체를 대상으로 한다"
    )
    parser.add_argument("--limit", type=_positive, help="읽을(정규화할) 최대 행 수")
    parser.add_argument("--dry-run", action="store_true", help="쓰지 않고 건수만 낸다")
    args = parser.parse_args(argv)
    if args.kind == "event" and args.source is not None:
        parser.error("--source는 알럿 소스 이름이라 --kind event에서는 쓸 수 없다")

    def action(settings: Settings, conn: psycopg.Connection, _owner: str) -> Any:
        return reprocess(
            settings,
            conn,
            source=args.source,
            since=args.since,
            limit=args.limit,
            dry_run=args.dry_run,
            all_rows=args.all,
            kind=args.kind,
        )

    return _run_command(action, format_reprocess, reprocess_exit_code)


def _since(value: str) -> datetime:
    """시각 문자열을 읽는다. 시간대가 없으면 UTC다."""
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError("ISO 8601 시각이어야 한다") from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _positive(value: str) -> int:
    if not value.isdigit() or int(value) < 1:
        raise argparse.ArgumentTypeError("1 이상의 정수여야 한다")
    return int(value)


def _run_command(
    action: Callable[[Settings, psycopg.Connection, str], Any],
    format_result: Callable[[Any], str] = lambda result: _format(result),
    code: Callable[[Any], int] = lambda result: exit_code(result),
) -> int:
    """설정·DB 연결을 준비하고 실행 함수 하나를 호출한다."""
    try:
        settings = load_settings()
    except (ConfigError, OSError, tomllib.TOMLDecodeError) as error:
        print(f"설정 오류: {error}", file=sys.stderr)
        return 2
    try:
        load_tables()
    except MappingTableError as error:
        print(f"매핑표 오류: {error}", file=sys.stderr)
        return 2
    url = os.environ.get(DATABASE_URL_ENV)
    if not url:
        print(f"환경변수 {DATABASE_URL_ENV}가 필요하다", file=sys.stderr)
        return 2
    try:
        with psycopg.connect(
            url, autocommit=True, connect_timeout=settings.connect_timeout_seconds
        ) as conn:
            result = action(settings, conn, uuid.uuid4().hex)
    except psycopg.Error:
        print("DB에 접속하지 못했거나 조회·저장에 실패했다", file=sys.stderr)
        return 1
    print(format_result(result))
    return code(result)


def _format(result: RunResult) -> str:
    """실행 결과를 한 줄로 만든다. 실패 코드별 건수를 뒤에 붙인다.

    Args:
        result: run의 결과.
    """
    line = (
        f"claimed={result.claimed} succeeded={result.succeeded}"
        f" failed={result.failed} lease_lost={result.lease_lost}"
    )
    failures = " ".join(f"{code}={count}" for code, count in sorted(result.failures.items()))
    return f"{line} {failures}".rstrip()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
