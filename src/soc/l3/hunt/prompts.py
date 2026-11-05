"""4층 작업 프롬프트(src/soc/l3/prompts/). 버전은 파일 내용의 sha256이다."""

import hashlib
from pathlib import Path

from soc.agent import TaskPrompt

PROMPT_DIR = Path(__file__).resolve().parents[1] / "prompts"


def load_prompt(name: str) -> TaskPrompt:
    text = (PROMPT_DIR / f"{name}.md").read_text(encoding="utf-8")
    return TaskPrompt(text=text, version=hashlib.sha256(text.encode("utf-8")).hexdigest())
