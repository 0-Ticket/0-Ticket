"""P04의 Alert·Ticket 상태표와 확신도 경계를 확인한다."""

import json
from pathlib import Path

import pytest

from soc.l1.judge import decide

CASES = json.loads(
    (Path(__file__).parent / "fixtures" / "l1_judge" / "decisions.json").read_text(encoding="utf-8")
)


@pytest.mark.parametrize(
    "case", CASES, ids=lambda case: f"{case['subject']}-{case['decision']}-{case['confidence']}"
)
def test_p04_status_table(case: dict) -> None:
    """case는 대상·판정·확신도와 기대 상태가 담긴 fixture다."""
    verdict = {"decision": case["decision"], "confidence": case["confidence"]}
    assert decide(case["subject"], verdict, 0.8) == case["status"]
