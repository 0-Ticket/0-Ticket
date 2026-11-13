"""uv run python -m soc.pipeline: 활성화 파이프(#316).

정규화 → Ticket 생성 → L1 → L2를 한 프로세스에서 설정 간격으로 돌린다. 수집은 이 파이프에 넣지
않고(사람이 `soc.ingest`를 따로 실행한다), L3는 [executor.l3] 값과 관계없이 띄우지 않는다.
기동하면 먼저 준비 점검(DB·마이그레이션·Qdrant·임베더·LLM 실호출 1회·도구 설정)을 항목별
OK/FAIL로 출력하고, 하나라도 FAIL이면 단계를 띄우지 않고 종료 코드 4로 끝난다.
통과하면 "준비 완료, 수집 명령을 실행하세요"를 출력하고 종료 신호(Ctrl+C·SIGTERM)까지 대기한다.

종료 코드: 0 정상, 1 종료 대기 시간 초과, 2 설정 오류, 3 단계 스레드가 죽음, 4 준비 점검 실패.
`python -m soc.agent`는 바뀌지 않는다. 두 명령을 동시에 띄우면 L1·L2가 같은 건을 두 번 모델에
보낼 수 있다(막지 않는다).
"""

import argparse
import logging
import os
import sys
import threading
import tomllib
from collections.abc import Mapping
from pathlib import Path

from agents import set_tracing_disabled

from soc.agent.config import load_full_config
from soc.agent.executor import (
    Executor,
    ExecutorConfigError,
    Resolve,
    resolve_factory,
    run_executor,
)
from soc.pipeline.check import Probes, format_check, run_checks
from soc.pipeline.config import PipelineConfigError, build_executor_config
from soc.similar.runtime import install_service


def main(
    argv: list[str] | None = None,
    *,
    config_dir: Path | None = None,
    stop_event: threading.Event | None = None,
    resolve: Resolve = resolve_factory,
    probes: Probes | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    argparse.ArgumentParser(
        prog="python -m soc.pipeline",
        description="정규화·Ticket 생성·L1·L2를 준비 점검 뒤 한 프로세스에서 주기 실행한다",
    ).parse_args(argv)
    set_tracing_disabled(True)  # 진입점에서 끈다(D-022). 환경변수에 맡기지 않는다
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    def err(line: str) -> None:
        print(line, file=sys.stderr)

    try:
        config = build_executor_config(load_full_config(config_dir))
    except PipelineConfigError as exc:
        err(f"파이프 설정 오류: {exc}")
        return 2
    except (OSError, tomllib.TOMLDecodeError) as exc:
        err(f"설정 파일을 읽지 못했다({type(exc).__name__})")
        return 2

    checks = run_checks(config, probes or Probes(), os.environ if environ is None else environ)
    for check in checks:
        print(format_check(check), flush=True)
    if any(c.status == "FAIL" for c in checks):
        err("준비 점검에 실패했다. 단계를 띄우지 않는다")
        return 4

    try:
        install_service(config)  # 워커가 만들어지기 전에: L1 워커가 색인 함수를 받아 간다(#313)
        executor = Executor(config, resolve=resolve)
    except ExecutorConfigError as exc:
        err(f"실행기 설정 오류: {exc}")
        return 2
    return run_executor(
        executor,
        stop_event,
        started=lambda: print("준비 완료, 수집 명령을 실행하세요", flush=True),
    )


if __name__ == "__main__":
    sys.exit(main())
