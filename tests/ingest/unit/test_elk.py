"""ELK 조회(PIT + search_after)를 손으로 만든 응답으로 확인한다(#218). DB가 필요 없다."""

import json
from collections.abc import Iterator

import httpx
import pytest
from fake_elk import API_KEY, BASE_URL, EVENTS, FakeElk, fixture, make_settings, respond

from soc.ingest import elk
from soc.ingest.errors import IngestError

SORT = [{"@timestamp": "asc"}, {"_shard_doc": "asc"}]


def pages_of(
    fake: FakeElk, start_ms: int | None = None, *, sleep=lambda _: None, **settings
) -> list[list[dict]]:
    with fake.client() as client:
        return list(
            elk.iter_pages(client, make_settings(**settings), EVENTS, start_ms, sleep=sleep)
        )


def failure_of(
    fake: FakeElk, start_ms: int | None = None, *, sleep=lambda _: None, **settings
) -> str:
    with pytest.raises(IngestError) as caught:
        pages_of(fake, start_ms, sleep=sleep, **settings)
    return caught.value.kind


def test_client_sends_api_key_and_does_not_follow_redirects() -> None:
    with elk.make_client(make_settings(), BASE_URL, API_KEY) as client:
        assert client.headers["Authorization"] == f"ApiKey {API_KEY}"
        assert client.follow_redirects is False
        assert client.base_url == httpx.URL(BASE_URL)
        assert client.timeout.connect == 5
        assert client.timeout.read == 5


def test_pages_follow_search_after_and_hits_are_untouched() -> None:
    fake = FakeElk({"logs-web-*": ["elk_events_page1.json", "elk_events_page2.json"]})
    pages = pages_of(fake)

    expected = [
        fixture("elk_events_page1.json")["hits"]["hits"],
        fixture("elk_events_page2.json")["hits"]["hits"],
    ]
    assert pages == expected  # hit 객체를 바꾸지 않는다
    assert fake.calls() == [
        "POST /logs-web-*/_pit",
        "POST /_search",
        "POST /_search",
        "DELETE /_pit",
    ]
    assert fake.requests[0].url.params["keep_alive"] == "1m"
    first, second = fake.search_bodies()
    assert first == {
        "size": 2,
        "pit": {"id": "pit-logs-web-*", "keep_alive": "1m"},
        "sort": SORT,
        "track_total_hits": False,
        # 체크포인트가 없으면 시각 필드가 있는 문서 전체. 시각이 없는 문서는 커서를 만들 수 없다
        "query": {"exists": {"field": "@timestamp"}},
    }
    assert second["search_after"] == [1793754000000, 12]  # 앞 페이지 마지막 hit의 sort
    assert second["pit"]["id"] == "pit-synthetic-2"  # 앞 응답이 준 PIT ID를 쓴다
    assert {k: v for k, v in second.items() if k not in ("search_after", "pit")} == {
        k: v for k, v in first.items() if k != "pit"
    }
    assert json.loads(fake.requests[-1].content) == {"id": "pit-synthetic-3"}


def test_full_page_asks_again_and_empty_page_ends() -> None:
    fake = FakeElk({"logs-web-*": ["elk_events_page1.json", "elk_empty.json"]})
    assert len(pages_of(fake)) == 1
    assert fake.calls().count("POST /_search") == 2


def test_start_time_becomes_range_gte() -> None:
    fake = FakeElk({"logs-web-*": ["elk_empty.json"]})
    assert pages_of(fake, start_ms=1793754000000) == []
    (body,) = fake.search_bodies()
    assert body["query"] == {
        "range": {"@timestamp": {"gte": 1793754000000, "format": "epoch_millis"}}
    }
    assert "search_after" not in body
    assert fake.calls()[-1] == "DELETE /_pit"


@pytest.mark.parametrize(
    ("status", "kind"), [(401, "auth"), (403, "auth"), (400, "http_status"), (302, "http_status")]
)
def test_search_status_is_failure_and_pit_is_closed(status: int, kind: str) -> None:
    fake = FakeElk({"logs-web-*": [respond(status, {"error": "SECRET-BODY"})]})
    assert failure_of(fake) == kind
    assert fake.calls()[-1] == "DELETE /_pit"


def test_pit_open_status_is_failure() -> None:
    fake = FakeElk({})
    fake.pit_response = respond(401, {"error": "nope"})
    assert failure_of(fake) == "auth"
    assert fake.calls() == ["POST /logs-web-*/_pit"]  # 열지 못한 PIT는 닫지 않는다


def test_redirect_is_not_followed() -> None:
    fake = FakeElk({})
    fake.pit_response = httpx.Response(302, headers={"Location": "https://other.example.com/"})
    assert failure_of(fake) == "http_status"
    assert len(fake.requests) == 1


def test_failed_close_does_not_hide_pages() -> None:
    """PIT는 keep_alive가 지나면 저절로 닫힌다. 닫기 실패로 받은 페이지를 버리지 않는다."""
    fake = FakeElk({"logs-web-*": ["elk_events_page2.json"]})
    fake.close_response = respond(500, {"error": "x"})
    assert len(pages_of(fake)) == 1
    assert fake.calls().count("DELETE /_pit") == 1


def test_oversized_response_is_too_large() -> None:
    def chunks() -> Iterator[bytes]:
        for _ in range(100):
            yield b" " * 100

    fake = FakeElk({"logs-web-*": [httpx.Response(200, content=chunks())]})
    assert failure_of(fake, max_bytes=1000) == "too_large"
    assert fake.calls()[-1] == "DELETE /_pit"


def test_request_timeout_and_network_error() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    for handler, kind in ((timeout, "timeout"), (refused, "network")):
        with httpx.Client(base_url=BASE_URL, transport=httpx.MockTransport(handler)) as client:
            with pytest.raises(IngestError) as caught:
                list(elk.iter_pages(client, make_settings(), EVENTS, None, sleep=lambda _: None))
        assert caught.value.kind == kind


def test_slow_response_stops_at_deadline() -> None:
    now = [0.0]

    def slow() -> Iterator[bytes]:
        for _ in range(100):
            now[0] += 5.0
            yield b" "

    fake = FakeElk({"logs-web-*": [httpx.Response(200, content=slow()) for _ in range(3)]})
    delays: list[float] = []
    with fake.client() as client, pytest.raises(IngestError) as caught:
        list(
            elk.iter_pages(
                client,
                make_settings(),
                EVENTS,
                None,
                clock=lambda: now[0],
                sleep=delays.append,
            )
        )
    assert caught.value.kind == "timeout"
    assert now[0] < 100 * 5.0
    assert fake.calls().count("POST /_search") == 3
    assert delays == [1.0, 1.0]


def hit(**change) -> dict:
    base = {"_index": "logs-a", "_id": "1", "_source": {}, "sort": [1793754000000, 1]}
    base.update(change)
    return {key: value for key, value in base.items() if value is not None}


@pytest.mark.parametrize(
    "answer",
    [
        httpx.Response(200, content=b"not json"),
        respond(200, []),
        respond(200, {"pit_id": "p", "hits": {}}),
        respond(200, {"pit_id": "p", "hits": {"hits": {}}}),
        respond(200, {"hits": {"hits": [hit()]}}),  # pit_id 없음
    ],
)
def test_malformed_search_response_is_response_shape(answer: httpx.Response) -> None:
    assert failure_of(FakeElk({"logs-web-*": [answer]})) == "response_shape"


def test_fixture_without_sort_is_sort_value() -> None:
    assert failure_of(FakeElk({"logs-web-*": ["elk_malformed.json"] * 3})) == "sort_value"


@pytest.mark.parametrize("body", [{}, {"id": ""}, {"id": 1}, []])
def test_malformed_pit_response_is_response_shape(body) -> None:
    fake = FakeElk({})
    fake.pit_response = respond(200, body)
    assert failure_of(fake) == "response_shape"
