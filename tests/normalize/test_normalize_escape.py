"""정규화 결과의 NUL·짝 없는 서로게이트를 6글자 이스케이프로 바꾸는 치환을 확인한다(#277, D-049).

치환은 문자열 값과 dict 키 모두에 적용하고, 다른 타입은 그대로 둔다.
"""

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from soc.contracts import validate_contract
from soc.ids import new_id
from soc.normalize.mapping import RawRow, normalize
from soc.normalize.ocsf_schema import validate_ocsf
from soc.normalize.run import escape_unstorable

CASES = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "normalize" / "raw.json").read_text(
        encoding="utf-8"
    )
)


def walk(value: Any):
    """값 안의 모든 문자열(값과 키)을 돌려준다."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from walk(key)
            yield from walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from walk(item)


def test_nul_and_lone_surrogates_are_replaced_in_values_and_keys() -> None:
    value = {
        "message": "before\x00after",
        "labels": {"low\udc00": "high\ud83d", "nested": ["x\x00", {"k\x00": "ok"}]},
    }

    result = escape_unstorable(value)

    assert result == {
        "message": "before\\u0000after",
        "labels": {"low\\udc00": "high\\ud83d", "nested": ["x\\u0000", {"k\\u0000": "ok"}]},
    }
    for text in walk(result):
        assert "\x00" not in text
        assert not any("\ud800" <= ch <= "\udfff" for ch in text)


def test_other_values_are_kept_as_they_are() -> None:
    when = datetime(2026, 11, 4, 1, 0, tzinfo=UTC)
    value = {"n": 3, "flag": True, "none": None, "when": when, "path": "C:\\temp\\u0000"}

    result = escape_unstorable(value)

    assert result == value
    assert result["when"] is when


def test_input_is_not_modified() -> None:
    value = {"message": "a\x00b"}

    escape_unstorable(value)

    assert value == {"message": "a\x00b"}


def test_normalized_alert_with_nul_and_surrogates_passes_contract() -> None:
    """NUL과 짝 없는 서로게이트가 든 알럿도 치환 뒤에는 계약과 OCSF 검사를 통과한다."""
    case = next(c for c in CASES if c["kind"] == "alert" and "error" not in c["expect"])
    original = copy.deepcopy(case["original"])
    source = original["_source"]
    source["kibana.alert.rule.name"] = "Web\x00scan\ud83d"
    source["host.name"] = "web\x00-01"

    mapped = normalize(RawRow(id=new_id("raw"), kind="alert", original=original))
    row = {**escape_unstorable(mapped.row), "assets": []}

    for text in walk(row):
        assert "\x00" not in text
        assert not any("\ud800" <= ch <= "\udfff" for ch in text)
    assert row["title"] == "Web\\u0000scan\\ud83d"
    validate_ocsf(row["ocsf"])
    validate_contract(mapped.kind, row)
