"""ELK 요청과 페이지 재시도 예산을 고정한다."""

import httpx
import pytest
from fake_elk import EVENTS, FakeElk, fixture, make_settings, respond

from soc.ingest import elk
from soc.ingest.errors import IngestError


def read(fake: FakeElk, delays: list[float]) -> list[list[dict]]:
    with fake.client() as client:
        return list(elk.iter_pages(client, make_settings(), EVENTS, None, sleep=delays.append))


def test_pit_open_retries_and_injects_fixed_delay() -> None:
    fake = FakeElk({"logs-web-*": ["elk_empty.json"]})
    fake.pit_responses = [respond(503, {"error": "hidden"}), respond(200, {"id": "pit-ready"})]
    delays: list[float] = []

    assert read(fake, delays) == []

    assert fake.calls() == [
        "POST /logs-web-*/_pit",
        "POST /logs-web-*/_pit",
        "POST /_search",
        "DELETE /_pit",
    ]
    assert delays == [1.0]


@pytest.mark.parametrize("status", [408, 429, 500, 503, 599])
def test_search_retries_transient_status_three_total_attempts(status: int) -> None:
    fake = FakeElk({"logs-web-*": [respond(status, {"error": "hidden"})] * 2 + ["elk_empty.json"]})
    delays: list[float] = []

    assert read(fake, delays) == []

    assert fake.calls().count("POST /_search") == 3
    assert delays == [1.0, 1.0]


def test_sort_page_retry_keeps_same_search_after_boundary() -> None:
    valid_page = fixture("elk_bad_sort_middle.json")
    valid_page["hits"]["hits"][1]["sort"][0] = 1793754030000
    fake = FakeElk(
        {
            "logs-web-*": [
                respond(200, valid_page),
                "elk_bad_sort_middle.json",
                "elk_bad_sort_middle.json",
                "elk_bad_sort_middle.json",
                "elk_empty.json",
            ]
        }
    )
    delays: list[float] = []

    pages = read(fake, delays)

    bodies = fake.search_bodies()
    assert len(pages) == 2
    assert [body["search_after"] for body in bodies[1:4]] == [
        [1793754060000, 13],
        [1793754060000, 13],
        [1793754060000, 13],
    ]
    assert delays == [1.0, 1.0]


@pytest.mark.parametrize("kind", ["network", "timeout"])
def test_search_retries_network_and_timeout_errors(kind: str) -> None:
    def fail(request: httpx.Request) -> httpx.Response:
        if kind == "network":
            raise httpx.ConnectError("transient", request=request)
        raise httpx.ReadTimeout("transient", request=request)

    fake = FakeElk({"logs-web-*": [fail, "elk_empty.json"]})
    delays: list[float] = []

    assert read(fake, delays) == []

    assert fake.calls().count("POST /_search") == 2
    assert delays == [1.0]


def test_search_exhaustion_preserves_http_status_kind() -> None:
    fake = FakeElk({"logs-web-*": [respond(503, {})] * 3})
    delays: list[float] = []

    with fake.client() as client, pytest.raises(IngestError) as caught:
        list(elk.iter_pages(client, make_settings(), EVENTS, None, sleep=delays.append))

    assert caught.value.kind == "http_status"
    assert fake.calls().count("POST /_search") == 3
    assert fake.calls()[-1] == "DELETE /_pit"
    assert delays == [1.0, 1.0]


def test_response_shape_is_not_retried() -> None:
    fake = FakeElk({"logs-web-*": [httpx.Response(200, content=b"not json")]})
    delays: list[float] = []

    with fake.client() as client, pytest.raises(IngestError) as caught:
        list(elk.iter_pages(client, make_settings(), EVENTS, None, sleep=delays.append))

    assert caught.value.kind == "response_shape"
    assert fake.calls().count("POST /_search") == 1
    assert delays == []
