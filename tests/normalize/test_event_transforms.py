"""4002 이벤트 표에서 사용하는 변환의 입력과 출력을 확인한다."""

import json
from pathlib import Path

import pytest

from soc.normalize.errors import NormalizeError
from soc.normalize.transforms import TRANSFORMS


@pytest.mark.parametrize(
    ("raw", "method", "name"),
    [("get", "GET", "GET"), ("pAtCh", "PATCH", "PATCH"), ("propfind", None, "PROPFIND")],
)
def test_http_method(raw, method, name):
    assert TRANSFORMS["http_method"].convert(raw) == method
    assert TRANSFORMS["method_name"].convert(raw) == name


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (0, 0),
        (-1, -1),
        ("000404", 404),
        ("123456789", 123456789),
        ("1234567890", None),
        ("-1", None),
        (" 200", None),
        (2.0, None),
    ],
)
def test_to_int(raw, expected):
    transform = TRANSFORMS["to_int"]
    assert transform.accepts(raw)
    assert transform.convert(raw) == expected


def test_to_int_discards_invalid_status_codes_from_fixture():
    fixture = Path(__file__).parents[1] / "fixtures" / "normalize" / "raw.json"
    cases = json.loads(fixture.read_text(encoding="utf-8"))
    status_codes = [
        case["original"]["_source"]["http"]["response"]["status_code"]
        for case in cases
        if case["case"].startswith("web_status_code_")
    ]
    assert len(status_codes) == 3
    assert all(TRANSFORMS["to_int"].convert(code) is None for code in status_codes)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ({"lat": 37.5, "lon": 127}, [127, 37.5]),
        ({"lat": 0, "lon": -73.5}, [-73.5, 0]),
        ({"lat": 37.5}, None),
        ({"lat": True, "lon": 0}, None),
        ({"lat": 0, "lon": float("inf")}, None),
        ({"lat": float("nan"), "lon": 0}, None),
        ({"lat": 0, "lon": 10**400}, None),
        ({"lat": "37.5", "lon": 0}, None),
        ([127, 37.5], None),
    ],
)
def test_geo_coordinates(raw, expected):
    transform = TRANSFORMS["geo_coordinates"]
    assert transform.accepts(raw)
    assert transform.convert(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("Thu Nov 19 15:49:58 2026", 1795103398000), ("Thu Jan  1 00:00:00 1970", 0)],
)
def test_ctime_utc(raw, expected):
    assert TRANSFORMS["ctime_utc"].convert(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        "",
        "Wut Nov 19 15:49:58 2026",
        "Thu Foo 19 15:49:58 2026",
        "Thu Nov 31 15:49:58 2026",
        "Thu Nov 19 24:49:58 2026",
        123,
        [],
    ],
)
def test_ctime_utc_rejects_malformed_present_values(raw):
    transform = TRANSFORMS["ctime_utc"]
    assert transform.accepts(raw)
    with pytest.raises(NormalizeError, match="validation_failed"):
        transform.convert(raw)
