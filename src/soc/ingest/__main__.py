"""uv run python -m soc.ingest [--since 24h]: 설정의 ELK 조회 대상을 한 번 수집하고 끝난다.

주기 실행은 운영 환경의 cron이 한다. 수집 명령은 DB 잠금으로 동시에 하나만 돈다.
--since는 30m·24h·7d 또는 시간대가 있는 ISO 8601 시각이다. 체크포인트가 없으면 그 시각부터,
있으면 체크포인트보다 이를 때만 그 시각부터 다시 읽는다(중복은 저장하지 않고 체크포인트는
후퇴하지 않는다). 첫 실행의 기본 범위와 겹침 구간은 [ingest]의 설정이다(D-057).

ELK 주소와 API 키는 [ingest]의 url_env·api_key_env가 가리키는 환경변수, DB 주소는 DATABASE_URL이다.
마이그레이션은 하지 않는다(uv run python -m soc.db.migrate를 먼저 실행한다).
종료 코드: 0 모두 성공, 1 실패한 대상이 있거나 DB 오류, 2 설정·환경변수·인자 오류,
3 다른 수집이 실행 중.
"""

import argparse
import os
import sys
import time

import httpx
import psycopg

from soc.ingest import elk, store
from soc.ingest.config import ConfigError, Settings, load_config, parse_since, read_settings
from soc.ingest.run import exit_code, format_footer, format_results, run


def _env(name: str) -> str:
    """환경변수 값을 돌려준다. 없거나 비었으면 ConfigError(값은 쓰지 않는다)."""
    value = os.environ.get(name)
    if not value:
        raise ConfigError(f"환경변수 {name}이 없다. .env.example을 참고해 설정한다.")
    return value


def _elk_env(settings: Settings) -> tuple[str, str]:
    """ELK 주소와 API 키를 환경변수에서 읽는다. 주소는 http(s)만 받는다.

    인자:
        settings: url_env, api_key_env 이름을 담은 설정.

    반환:
        (ELK 주소, API 키).

    발생:
        ConfigError: 환경변수가 없거나, 주소가 http(s)가 아니거나, 계정 정보를 담고 있을 때.
    """
    base_url = _env(settings.url_env)
    try:
        url = httpx.URL(base_url)
    except httpx.InvalidURL:
        url = None
    if url is None or url.scheme not in ("http", "https") or not url.host or url.userinfo:
        # 주소에 비밀이 들어 있을 수 있어 값은 쓰지 않는다.
        raise ConfigError(f"환경변수 {settings.url_env}는 계정 정보 없는 http(s) 주소여야 한다")
    return base_url, _env(settings.api_key_env)


def main(argv: list[str] | None = None) -> int:
    """설정을 읽고 한 번 수집한다. 종료 코드를 돌려준다.

    인자:
        argv: 명령줄 인자(--since). None이면 인자 없음이다(sys.argv를 읽지 않는다).

    반환:
        0 모두 성공, 1 실패한 대상이 있거나 DB 오류, 2 설정·환경변수·인자 오류,
        3 다른 수집이 실행 중.
    """
    parser = argparse.ArgumentParser(prog="python -m soc.ingest", description=__doc__)
    parser.add_argument("--since", help="조회 시작 시각: 30m·24h·7d 또는 시간대가 있는 ISO 8601")
    args = parser.parse_args([] if argv is None else argv)
    try:
        settings = read_settings(load_config()["ingest"])
        since_ms = None
        if args.since is not None:
            try:
                since_ms = parse_since(args.since, now_ms=int(time.time() * 1000))
            except ConfigError as exc:
                raise ConfigError(f"--since: {exc}") from None
        base_url, api_key = _elk_env(settings)
        database_url = _env("DATABASE_URL")
        # CA 파일을 연결 전에 한 번 읽어 본다. 못 읽으면 원본·체크포인트·이력을 쓰지 않고 끝낸다.
        elk.tls_verify(settings)
    except ConfigError as exc:
        print(f"설정 오류: {exc}", file=sys.stderr)
        return 2
    try:
        with (
            psycopg.connect(database_url, autocommit=True) as conn,
            elk.make_client(settings, base_url, api_key) as client,
        ):
            # ELK에 붙기 전에 잡는다. 못 잡으면 아무것도 쓰지 않고 끝나고, 연결이 닫히면 풀린다.
            if not store.acquire_run_lock(conn):
                print("다른 수집이 실행 중이다. 끝난 뒤 다시 실행한다", file=sys.stderr)
                return 3
            results = run(settings, conn, client, since_ms=since_ms)
    except psycopg.Error as exc:
        # 원래 예외 메시지에는 접속 대상 주소가 들어 있을 수 있어 종류만 남긴다.
        reason = type(exc).__name__
        print(f"DB 오류({reason}). DATABASE_URL과 마이그레이션을 확인한다", file=sys.stderr)
        return 1
    for line in [*format_results(results), *format_footer(results)]:
        print(line)
    return exit_code(results)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
