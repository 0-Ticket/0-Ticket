"""uv run python -m soc.agent: 실행기(#215). 설명은 soc.agent.executor에 있다."""

import sys

from soc.agent.executor import main

if __name__ == "__main__":
    sys.exit(main())
