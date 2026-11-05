"""실패한 정규화 원본을 한 번 실행해 다시 처리한다.

uv run python -m soc.normalize.retry
"""

import sys

from soc.normalize.__main__ import _run_command
from soc.normalize.run import run_failed


def main() -> int:
    """실패 자료를 한 묶음 재처리한다."""
    return _run_command(run_failed)


if __name__ == "__main__":
    sys.exit(main())
