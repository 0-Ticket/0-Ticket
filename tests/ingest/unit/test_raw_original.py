"""RawRecord 원본을 JSON 글자(original_text)로 바꾸는 방식을 손으로 만든 샘플로 확인한다(#277).

원본은 json.dumps(ensure_ascii=True)로 만들므로 NUL·짝 없는 서로게이트·백슬래시가 이스케이프 글자로
들어가고, json.loads로 원래 hit가 그대로 되살아나야 한다. DB 없이 _raw_record만 본다.
"""

import json
from pathlib import Path

import pytest
from fake_elk import EVENTS, make_settings

from soc.ids import siem_ref_key
from soc.ingest import run

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "ingest"
FETCHED_AT = 1793754000000


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def raw_record(hit: dict) -> dict:
    return run._raw_record(make_settings(EVENTS), EVENTS, hit, FETCHED_AT)


@pytest.mark.parametrize(
    "name",
    ["nul_doc.json", "lone_surrogate_doc.json", "backslash_doc.json", "normal_doc.json"],
)
def test_original_text_restores_the_hit_exactly(name: str) -> None:
    hit = load(name)
    record = raw_record(hit)

    text = record["original_text"]
    assert isinstance(text, str)
    assert text.startswith("{")
    # ensure_ascii=True라 저장되는 글자는 ASCII뿐이다. NUL·서로게이트는 이스케이프 글자로 들어간다
    assert text.isascii()
    assert json.loads(text) == hit
    assert "original" not in record


def test_nul_and_lone_surrogate_are_stored_as_escape_text() -> None:
    nul = raw_record(load("nul_doc.json"))["original_text"]
    surrogate = raw_record(load("lone_surrogate_doc.json"))["original_text"]

    assert "\\u0000" in nul
    assert "\\ud83d" in surrogate
    assert "\\udc00" in surrogate
    assert "\x00" not in nul


def test_siem_ref_of_a_plain_hit_is_index_and_id() -> None:
    record = raw_record(load("normal_doc.json"))

    assert record["siem_ref"] == ".ds-logs-web-default-2026.11.04-000001/evt-plain"


def test_siem_ref_is_json_escaped_without_quotes() -> None:
    hit = {"_index": "idx", "_id": 'a"b\\c', "_source": {}}
    record = raw_record(hit)

    # JSON 문자열 이스케이프를 한 뒤 양쪽 따옴표만 뺀 값이다
    assert record["siem_ref"] == 'idx/a\\"b\\\\c'
    assert record["siem_ref"] == json.dumps("idx/" + 'a"b\\c')[1:-1]


def test_siem_ref_escapes_nul_as_six_characters() -> None:
    hit = {"_index": "idx", "_id": "x\u0000y", "_source": {}}
    record = raw_record(hit)

    assert record["siem_ref"] == "idx/x\\u0000y"
    assert "\x00" not in record["siem_ref"]


def test_siem_ref_of_odd_id_is_the_shared_key_helper() -> None:
    # 따옴표·백슬래시·제어문자·한글 _id도 soc.ids.siem_ref_key와 같은 저장 키가 된다(#277)
    hit = load("odd_id_doc.json")
    record = raw_record(hit)

    assert record["siem_ref"] == siem_ref_key(f"{hit['_index']}/{hit['_id']}")
    assert record["siem_ref"].isascii()
    assert json.loads(record["original_text"]) == hit
