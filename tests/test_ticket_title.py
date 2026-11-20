"""Ticket 제목 규칙(#343, D-070). 샘플은 tests/fixtures/tickets/title_cases.json이다."""

import json
import re
from pathlib import Path
from typing import Any

import pytest
from contract_samples import load, load_schema

from soc.contracts import validate_contract
from soc.l3.hunt.verify import _ticket
from soc.ticketing import FALLBACK_TITLE, TITLE_SPACES, clean_title, ticket_title

CASES = json.loads(
    (Path(__file__).parent / "fixtures" / "tickets" / "title_cases.json").read_text(
        encoding="utf-8"
    )
)


def expand(value: Any) -> Any:
    """{"repeat", "times", "lead", "tail", "join"} 꼴을 긴 문자열로 펼친다."""
    if not isinstance(value, dict):
        return value
    body = value.get("join", "").join([value["repeat"]] * value["times"])
    return value.get("lead", "") + body + value.get("tail", "")


CLEAN = [(c["case"], expand(c["input"]), expand(c["expected"])) for c in CASES["clean"]]


def test_fallback_title_is_fixed() -> None:
    assert FALLBACK_TITLE == "(제목 없음)"


@pytest.mark.parametrize(("case", "text", "expected"), CLEAN, ids=[c[0] for c in CLEAN])
def test_clean_title(case: str, text: str, expected: str) -> None:
    assert clean_title(text) == expected


@pytest.mark.parametrize(("case", "text", "expected"), CLEAN, ids=[c[0] for c in CLEAN])
def test_clean_title_output_passes_the_ticket_contract(case: str, text: str, expected: str) -> None:
    """어떤 입력이든 결과가 계약을 통과한다. 어긋나면 run()이 같은 alert를 다시 시도한다(D-059)."""
    ticket = {**load("valid", "ticket")[0]["data"], "title": clean_title(text)}
    validate_contract("ticket", ticket)


@pytest.mark.parametrize("case", CASES["pick"], ids=[c["case"] for c in CASES["pick"]])
def test_ticket_title(case: dict[str, Any]) -> None:
    alerts = [{**a, "title": expand(a["title"])} for a in case["alerts"]]
    before = json.dumps(alerts, ensure_ascii=False)

    assert ticket_title(alerts) == expand(case["expected"])
    assert ticket_title(list(reversed(alerts))) == expand(case["expected"])  # 입력 순서와 무관
    assert json.dumps(alerts, ensure_ascii=False) == before  # 입력을 바꾸지 않는다


def test_contract_title_bounds() -> None:
    schema = load_schema("ticket.schema.json")
    title = schema["properties"]["title"]

    assert "title" in schema["required"]
    assert (title["type"], title["minLength"], title["maxLength"]) == ("string", 1, 200)


def test_contract_pattern_uses_the_same_spaces_as_clean_title() -> None:
    """계약 pattern이 공백으로 보는 글자와 clean_title의 공백 목록이 정확히 같다(BMP 전체)."""
    pattern = re.compile(load_schema("ticket.schema.json")["properties"]["title"]["pattern"])

    outside = {chr(code) for code in range(0x10000) if not pattern.search(chr(code))}

    assert outside == set(TITLE_SPACES)
    assert len(TITLE_SPACES) == 8


@pytest.mark.parametrize(("case", "text", "expected"), CLEAN, ids=[c[0] for c in CLEAN])
def test_l3_ticket_title_is_the_cleaned_hypothesis(case: str, text: str, expected: str) -> None:
    hunt = {"id": "hnt_01a19f93-1150-7000-8000-000000000001", "hypothesis": text, "entities": []}

    ticket = _ticket(hunt, 1_793_680_000_000)

    assert ticket["title"] == expected
    validate_contract("ticket", ticket)  # 빈 가설이어도 계약을 통과한다(폴백)
